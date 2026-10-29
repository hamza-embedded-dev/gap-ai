#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Canonical Audio Feedback Events for GAP-AI Assistant
 *
 * Each event category produces a distinct, recognizable acoustic cue:
 * - PTT_START: Radio-inspired activation chirp (1300 -> 1900 Hz, 25 ms)
 * - RECORDING_SUBMITTED: Subtle dispatch chirp (1800 -> 1200 Hz, 30 ms)
 * - WIFI_CONNECTED: Melodic 3-tone arpeggio (C5 -> E5 -> G5, 120 ms)
 * - WIFI_DISCONNECTED: Gentle downward two-tone warning (440 -> 330 Hz, 100 ms)
 * - WIFI_SETUP_OPENED: Three rising alert steps (440 -> 660 -> 880 Hz, 120 ms)
 * - WIFI_SETUP_SUCCESS: Affirmative double chime (784 -> 1046 Hz, 100 ms)
 * - BACKEND_CONNECTED: Rising affirmative chime (880 -> 1175 Hz, 90 ms)
 * - BACKEND_UNAVAILABLE: Low dual buzz warning (300 -> 200 Hz, 140 ms)
 * - RESPONSE_PROCESSING: Fast subtle tick cue
 * - RESPONSE_READY: Subtle ready blip
 * - OPERATION_SUCCESS: Crisp high affirmation chime (1046 -> 1318 Hz, 100 ms)
 * - OPERATION_ERROR: Low error buzz (330 -> 220 Hz, 140 ms)
 * - MODE_PLAN: Plan Mode signature tone (1000 -> 750 Hz, 120 ms)
 * - MODE_COACH: Coach Mode signature arpeggio (600 -> 900 -> 1200 Hz, 140 ms)
 */
typedef enum {
    AUDIO_FEEDBACK_NONE = 0,
    AUDIO_FEEDBACK_PTT_START,
    AUDIO_FEEDBACK_RECORDING_SUBMITTED,
    AUDIO_FEEDBACK_WIFI_CONNECTED,
    AUDIO_FEEDBACK_WIFI_DISCONNECTED,
    AUDIO_FEEDBACK_WIFI_SETUP_OPENED,
    AUDIO_FEEDBACK_WIFI_SETUP_SUCCESS,
    AUDIO_FEEDBACK_BACKEND_CONNECTED,
    AUDIO_FEEDBACK_BACKEND_UNAVAILABLE,
    AUDIO_FEEDBACK_RESPONSE_PROCESSING,
    AUDIO_FEEDBACK_RESPONSE_READY,
    AUDIO_FEEDBACK_OPERATION_SUCCESS,
    AUDIO_FEEDBACK_OPERATION_ERROR,
    AUDIO_FEEDBACK_MODE_PLAN,
    AUDIO_FEEDBACK_MODE_COACH,
    AUDIO_FEEDBACK_COUNT,
} audio_feedback_event_t;

/**
 * @brief Priority classification for sound suppression and arbitration
 */
typedef enum {
    AUDIO_PRIO_IDLE = 0,
    AUDIO_PRIO_STATUS = 1,       // Wi-Fi / backend polling status (lowest priority, suppressed during speech/proposals)
    AUDIO_PRIO_USER_ACTION = 2,   // PTT button, confirmation clicks, mode changes
    AUDIO_PRIO_PROPOSAL = 3,      // Active unconfirmed plan awaiting user choice
    AUDIO_PRIO_SPEECH = 4,        // Spoken audio playback in progress (highest priority)
} audio_feedback_priority_t;

/**
 * @brief Initialize the audio feedback subsystem and debounce timers
 */
void audio_feedback_init(void);

/**
 * @brief Play an audio feedback event adhering to priority and debounce rules
 *
 * @param event The event to trigger
 * @return true if sound was successfully emitted, false if suppressed or bypassed
 */
bool audio_feedback_play(audio_feedback_event_t event);

/**
 * @brief Notify feedback subsystem that live speech (TTS playback) is active
 * When active, all routine status sounds (Wi-Fi, health checks) are strictly suppressed.
 */
void audio_feedback_set_speech_active(bool active);

/**
 * @brief Check if speech playback is currently active
 */
bool audio_feedback_is_speech_active(void);

/**
 * @brief Notify feedback subsystem that a plan proposal is awaiting user confirmation
 * While pending, background status sounds are suppressed to avoid distracting the user.
 */
void audio_feedback_set_proposal_pending(bool pending);

/**
 * @brief Check if a plan proposal confirmation is currently pending
 */
bool audio_feedback_is_proposal_pending(void);

/**
 * @brief Get the configured priority level for an event
 */
audio_feedback_priority_t audio_feedback_get_priority(audio_feedback_event_t event);

/**
 * @brief Get human-readable name of an audio feedback event
 */
const char *audio_feedback_get_name(audio_feedback_event_t event);

/**
 * @brief Reset all internal state and debounce tracking (useful in tests and reboots)
 */
void audio_feedback_reset(void);

#ifdef __cplusplus
}
#endif
