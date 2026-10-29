#include "audio_feedback.h"

#include <math.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#ifdef ESP_PLATFORM
#include "esp_log.h"
#include "esp_timer.h"
#include "board_pins.h"
#include "audio_play.h"
static const char *TAG = "audio_fb";
#define GET_TIME_MS() (int64_t)(esp_timer_get_time() / 1000)
#else
#include <stdio.h>
#include <stdlib.h>
static int64_t s_mock_time_ms = 0;
#define GET_TIME_MS() s_mock_time_ms
#define BOARD_HAS_VOICE_HW 1
#endif

#define SAMPLE_RATE_HZ 16000
#define CHUNK_SAMPLES  160
#define DEFAULT_DEBOUNCE_MS 4000

// Internal state tracking
static bool s_speech_active = false;
static bool s_proposal_pending = false;
static int64_t s_last_event_time[AUDIO_FEEDBACK_COUNT] = {0};

typedef struct {
    float freq_start;
    float freq_end;
    uint16_t duration_ms;
    uint16_t pause_ms;
} tone_step_t;

#define MAX_STEPS 4

typedef struct {
    audio_feedback_priority_t priority;
    uint32_t debounce_ms;
    uint8_t num_steps;
    tone_step_t steps[MAX_STEPS];
    const char *name;
} event_config_t;

static const event_config_t s_configs[AUDIO_FEEDBACK_COUNT] = {
    [AUDIO_FEEDBACK_NONE] = {
        .priority = AUDIO_PRIO_IDLE,
        .debounce_ms = 0,
        .num_steps = 0,
        .name = "NONE",
    },
    [AUDIO_FEEDBACK_PTT_START] = {
        .priority = AUDIO_PRIO_USER_ACTION,
        .debounce_ms = 150,
        .num_steps = 1,
        .steps = {
            {.freq_start = 1300.0f, .freq_end = 1900.0f, .duration_ms = 25, .pause_ms = 0},
        },
        .name = "PTT_START",
    },
    [AUDIO_FEEDBACK_RECORDING_SUBMITTED] = {
        .priority = AUDIO_PRIO_USER_ACTION,
        .debounce_ms = 150,
        .num_steps = 1,
        .steps = {
            {.freq_start = 1800.0f, .freq_end = 1200.0f, .duration_ms = 30, .pause_ms = 0},
        },
        .name = "RECORDING_SUBMITTED",
    },
    [AUDIO_FEEDBACK_WIFI_CONNECTED] = {
        .priority = AUDIO_PRIO_STATUS,
        .debounce_ms = DEFAULT_DEBOUNCE_MS,
        .num_steps = 3,
        .steps = {
            {.freq_start = 523.25f, .freq_end = 523.25f, .duration_ms = 35, .pause_ms = 5},  // C5
            {.freq_start = 659.25f, .freq_end = 659.25f, .duration_ms = 35, .pause_ms = 5},  // E5
            {.freq_start = 783.99f, .freq_end = 783.99f, .duration_ms = 45, .pause_ms = 0},  // G5
        },
        .name = "WIFI_CONNECTED",
    },
    [AUDIO_FEEDBACK_WIFI_DISCONNECTED] = {
        .priority = AUDIO_PRIO_STATUS,
        .debounce_ms = DEFAULT_DEBOUNCE_MS,
        .num_steps = 2,
        .steps = {
            {.freq_start = 440.0f, .freq_end = 440.0f, .duration_ms = 40, .pause_ms = 10},
            {.freq_start = 330.0f, .freq_end = 330.0f, .duration_ms = 60, .pause_ms = 0},
        },
        .name = "WIFI_DISCONNECTED",
    },
    [AUDIO_FEEDBACK_WIFI_SETUP_OPENED] = {
        .priority = AUDIO_PRIO_USER_ACTION,
        .debounce_ms = 1000,
        .num_steps = 3,
        .steps = {
            {.freq_start = 440.0f, .freq_end = 440.0f, .duration_ms = 40, .pause_ms = 10},
            {.freq_start = 660.0f, .freq_end = 660.0f, .duration_ms = 40, .pause_ms = 10},
            {.freq_start = 880.0f, .freq_end = 880.0f, .duration_ms = 50, .pause_ms = 0},
        },
        .name = "WIFI_SETUP_OPENED",
    },
    [AUDIO_FEEDBACK_WIFI_SETUP_SUCCESS] = {
        .priority = AUDIO_PRIO_USER_ACTION,
        .debounce_ms = 1000,
        .num_steps = 2,
        .steps = {
            {.freq_start = 783.99f, .freq_end = 783.99f, .duration_ms = 40, .pause_ms = 10},
            {.freq_start = 1046.50f, .freq_end = 1046.50f, .duration_ms = 60, .pause_ms = 0},
        },
        .name = "WIFI_SETUP_SUCCESS",
    },
    [AUDIO_FEEDBACK_BACKEND_CONNECTED] = {
        .priority = AUDIO_PRIO_STATUS,
        .debounce_ms = DEFAULT_DEBOUNCE_MS,
        .num_steps = 2,
        .steps = {
            {.freq_start = 880.0f, .freq_end = 880.0f, .duration_ms = 40, .pause_ms = 10},
            {.freq_start = 1174.66f, .freq_end = 1174.66f, .duration_ms = 60, .pause_ms = 0},
        },
        .name = "BACKEND_CONNECTED",
    },
    [AUDIO_FEEDBACK_BACKEND_UNAVAILABLE] = {
        .priority = AUDIO_PRIO_STATUS,
        .debounce_ms = DEFAULT_DEBOUNCE_MS,
        .num_steps = 2,
        .steps = {
            {.freq_start = 300.0f, .freq_end = 300.0f, .duration_ms = 60, .pause_ms = 15},
            {.freq_start = 200.0f, .freq_end = 200.0f, .duration_ms = 80, .pause_ms = 0},
        },
        .name = "BACKEND_UNAVAILABLE",
    },
    [AUDIO_FEEDBACK_RESPONSE_PROCESSING] = {
        .priority = AUDIO_PRIO_USER_ACTION,
        .debounce_ms = 500,
        .num_steps = 1,
        .steps = {
            {.freq_start = 1200.0f, .freq_end = 1600.0f, .duration_ms = 20, .pause_ms = 0},
        },
        .name = "RESPONSE_PROCESSING",
    },
    [AUDIO_FEEDBACK_RESPONSE_READY] = {
        .priority = AUDIO_PRIO_USER_ACTION,
        .debounce_ms = 500,
        .num_steps = 1,
        .steps = {
            {.freq_start = 1600.0f, .freq_end = 2000.0f, .duration_ms = 25, .pause_ms = 0},
        },
        .name = "RESPONSE_READY",
    },
    [AUDIO_FEEDBACK_OPERATION_SUCCESS] = {
        .priority = AUDIO_PRIO_USER_ACTION,
        .debounce_ms = 300,
        .num_steps = 2,
        .steps = {
            {.freq_start = 1046.50f, .freq_end = 1046.50f, .duration_ms = 40, .pause_ms = 10},
            {.freq_start = 1318.51f, .freq_end = 1318.51f, .duration_ms = 60, .pause_ms = 0},
        },
        .name = "OPERATION_SUCCESS",
    },
    [AUDIO_FEEDBACK_OPERATION_ERROR] = {
        .priority = AUDIO_PRIO_USER_ACTION,
        .debounce_ms = 300,
        .num_steps = 2,
        .steps = {
            {.freq_start = 330.0f, .freq_end = 330.0f, .duration_ms = 60, .pause_ms = 15},
            {.freq_start = 220.0f, .freq_end = 220.0f, .duration_ms = 80, .pause_ms = 0},
        },
        .name = "OPERATION_ERROR",
    },
    [AUDIO_FEEDBACK_MODE_PLAN] = {
        .priority = AUDIO_PRIO_USER_ACTION,
        .debounce_ms = 300,
        .num_steps = 2,
        .steps = {
            {.freq_start = 1000.0f, .freq_end = 1000.0f, .duration_ms = 50, .pause_ms = 15},
            {.freq_start = 750.0f,  .freq_end = 750.0f,  .duration_ms = 70, .pause_ms = 0},
        },
        .name = "MODE_PLAN",
    },
    [AUDIO_FEEDBACK_MODE_COACH] = {
        .priority = AUDIO_PRIO_USER_ACTION,
        .debounce_ms = 300,
        .num_steps = 3,
        .steps = {
            {.freq_start = 600.0f,  .freq_end = 600.0f,  .duration_ms = 40, .pause_ms = 10},
            {.freq_start = 900.0f,  .freq_end = 900.0f,  .duration_ms = 40, .pause_ms = 10},
            {.freq_start = 1200.0f, .freq_end = 1200.0f, .duration_ms = 60, .pause_ms = 0},
        },
        .name = "MODE_COACH",
    },
};

void audio_feedback_init(void)
{
    memset(s_last_event_time, 0, sizeof(s_last_event_time));
    s_speech_active = false;
    s_proposal_pending = false;
}

void audio_feedback_reset(void)
{
    audio_feedback_init();
}

void audio_feedback_set_speech_active(bool active)
{
    s_speech_active = active;
}

bool audio_feedback_is_speech_active(void)
{
    return s_speech_active;
}

void audio_feedback_set_proposal_pending(bool pending)
{
    s_proposal_pending = pending;
}

bool audio_feedback_is_proposal_pending(void)
{
    return s_proposal_pending;
}

audio_feedback_priority_t audio_feedback_get_priority(audio_feedback_event_t event)
{
    if (event <= AUDIO_FEEDBACK_NONE || event >= AUDIO_FEEDBACK_COUNT) {
        return AUDIO_PRIO_IDLE;
    }
    return s_configs[event].priority;
}

const char *audio_feedback_get_name(audio_feedback_event_t event)
{
    if (event <= AUDIO_FEEDBACK_NONE || event >= AUDIO_FEEDBACK_COUNT) {
        return "UNKNOWN";
    }
    return s_configs[event].name;
}

#ifndef ESP_PLATFORM
// Hook for host testing to record played feedback events
static audio_feedback_event_t s_last_played_event = AUDIO_FEEDBACK_NONE;
static uint32_t s_play_count = 0;

void audio_feedback_mock_set_time(int64_t now_ms)
{
    s_mock_time_ms = now_ms;
}

audio_feedback_event_t audio_feedback_mock_get_last_played(void)
{
    return s_last_played_event;
}

uint32_t audio_feedback_mock_get_play_count(void)
{
    return s_play_count;
}
#endif

bool audio_feedback_play(audio_feedback_event_t event)
{
    if (event <= AUDIO_FEEDBACK_NONE || event >= AUDIO_FEEDBACK_COUNT) {
        return false;
    }

    const event_config_t *cfg = &s_configs[event];
    int64_t now_ms = GET_TIME_MS();

    // 1. Suppression Rule 1: Live spoken speech is sacred
    // Never interrupt incoming TTS stream with routine status sounds
    if (s_speech_active && cfg->priority <= AUDIO_PRIO_USER_ACTION) {
#ifdef ESP_PLATFORM
        ESP_LOGD(TAG, "Suppressed %s: speech is currently active", cfg->name);
#endif
        return false;
    }

    // 2. Suppression Rule 2: Pending plan proposal
    // Background status events (Wi-Fi, health) must not distract from confirmation
    if (s_proposal_pending && cfg->priority <= AUDIO_PRIO_STATUS) {
#ifdef ESP_PLATFORM
        ESP_LOGD(TAG, "Suppressed %s: plan confirmation is pending", cfg->name);
#endif
        return false;
    }

    // 3. Debouncing Rule: Prevent repeated audio flooding
    if (cfg->debounce_ms > 0 && s_last_event_time[event] > 0) {
        int64_t elapsed = now_ms - s_last_event_time[event];
        if (elapsed < (int64_t)cfg->debounce_ms) {
#ifdef ESP_PLATFORM
            ESP_LOGD(TAG, "Debounced %s: %lld ms < %u ms", cfg->name, (long long)elapsed, (unsigned)cfg->debounce_ms);
#endif
            return false;
        }
    }

    s_last_event_time[event] = now_ms;

#ifndef ESP_PLATFORM
    s_last_played_event = event;
    s_play_count++;
    return true;
#else

#if BOARD_HAS_VOICE_HW
    if (audio_play_begin(SAMPLE_RATE_HZ) != ESP_OK) {
        return false;
    }

    int16_t chunk[CHUNK_SAMPLES];

    for (uint8_t step_idx = 0; step_idx < cfg->num_steps; step_idx++) {
        const tone_step_t *step = &cfg->steps[step_idx];
        int total_samples = (SAMPLE_RATE_HZ * step->duration_ms) / 1000;
        float freq_delta = (step->freq_end - step->freq_start) / (total_samples > 0 ? (float)total_samples : 1.0f);
        float current_phase = 0.0f;

        for (int done = 0; done < total_samples; done += CHUNK_SAMPLES) {
            int n = total_samples - done;
            if (n > CHUNK_SAMPLES) n = CHUNK_SAMPLES;

            for (int i = 0; i < n; i++) {
                float freq = step->freq_start + freq_delta * (float)(done + i);
                float phase_inc = (2.0f * (float)M_PI * freq) / (float)SAMPLE_RATE_HZ;
                current_phase += phase_inc;
                if (current_phase > 2.0f * (float)M_PI) {
                    current_phase -= 2.0f * (float)M_PI;
                }
                // Moderate base amplitude (8000), processed through limiter with scale 0.35f
                chunk[i] = (int16_t)(sinf(current_phase) * 8000.0f);
            }
            audio_play_write(chunk, n);
        }

        if (step->pause_ms > 0) {
            int pause_samples = (SAMPLE_RATE_HZ * step->pause_ms) / 1000;
            memset(chunk, 0, sizeof(chunk));
            for (int done = 0; done < pause_samples; done += CHUNK_SAMPLES) {
                int n = pause_samples - done;
                if (n > CHUNK_SAMPLES) n = CHUNK_SAMPLES;
                audio_play_write(chunk, n);
            }
        }
    }

    audio_play_end();
    return true;
#else
    return false;
#endif

#endif
}
