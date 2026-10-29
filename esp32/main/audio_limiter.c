#include "audio_limiter.h"

#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

void audio_limiter_init(audio_limiter_t *lim, float initial_scale, uint32_t sample_rate)
{
    if (!lim) {
        return;
    }
    lim->sample_rate = sample_rate > 0 ? sample_rate : 16000;
    lim->high_pass_hz = AUDIO_LIMITER_DEFAULT_HP_HZ;

    if (initial_scale < AUDIO_LIMITER_MIN_SCALE) {
        initial_scale = AUDIO_LIMITER_MIN_SCALE;
    } else if (initial_scale > AUDIO_LIMITER_MAX_SCALE) {
        initial_scale = AUDIO_LIMITER_MAX_SCALE;
    }
    lim->scale = initial_scale;

    if (lim->high_pass_hz > 0.0f) {
        float rc = 1.0f / (2.0f * (float)M_PI * lim->high_pass_hz);
        float dt = 1.0f / (float)lim->sample_rate;
        lim->hp_alpha = rc / (rc + dt);
    } else {
        lim->hp_alpha = 1.0f;
    }
    lim->hp_prev_in = 0.0f;
    lim->hp_prev_out = 0.0f;
    lim->fade_total = lim->sample_rate * AUDIO_LIMITER_DEFAULT_FADE_MS / 1000;
    lim->fade_done = 0;
    lim->peak_output = 0;
}

void audio_limiter_reset(audio_limiter_t *lim)
{
    if (!lim) {
        return;
    }
    lim->hp_prev_in = 0.0f;
    lim->hp_prev_out = 0.0f;
    lim->fade_done = 0;
}

void audio_limiter_set_scale(audio_limiter_t *lim, float scale)
{
    if (!lim) {
        return;
    }
    if (scale < AUDIO_LIMITER_MIN_SCALE) {
        scale = AUDIO_LIMITER_MIN_SCALE;
    } else if (scale > AUDIO_LIMITER_MAX_SCALE) {
        scale = AUDIO_LIMITER_MAX_SCALE;
    }
    lim->scale = scale;
}

float audio_limiter_get_scale(const audio_limiter_t *lim)
{
    return lim ? lim->scale : AUDIO_LIMITER_DEFAULT_SCALE;
}

void audio_limiter_set_high_pass(audio_limiter_t *lim, float hp_hz)
{
    if (!lim) {
        return;
    }
    lim->high_pass_hz = hp_hz;
    if (hp_hz > 0.0f) {
        float rc = 1.0f / (2.0f * (float)M_PI * hp_hz);
        float dt = 1.0f / (float)lim->sample_rate;
        lim->hp_alpha = rc / (rc + dt);
    } else {
        lim->hp_alpha = 1.0f;
    }
}

float audio_limiter_get_high_pass(const audio_limiter_t *lim)
{
    return lim ? lim->high_pass_hz : AUDIO_LIMITER_DEFAULT_HP_HZ;
}

int16_t audio_limiter_process_sample(audio_limiter_t *lim, int16_t sample)
{
    if (!lim) {
        return sample;
    }

    float x = (float)sample;
    float y;
    if (lim->high_pass_hz > 0.0f) {
        y = lim->hp_alpha * (lim->hp_prev_out + x - lim->hp_prev_in);
        lim->hp_prev_in = x;
        lim->hp_prev_out = y;
    } else {
        y = x;
    }

    // Apply digital volume scaling and optional fade-in
    float gain = lim->scale;
    if (lim->fade_total > 0 && lim->fade_done < lim->fade_total) {
        gain *= (float)lim->fade_done++ / (float)lim->fade_total;
    }

    float v = y * gain;

    // Hard ceiling strictly tied to current limiter scale
    float ceiling = 32767.0f * lim->scale;
    if (ceiling > 32767.0f) {
        ceiling = 32767.0f;
    } else if (ceiling < 0.0f) {
        ceiling = 0.0f;
    }

    if (v > ceiling) {
        v = ceiling;
    } else if (v < -ceiling) {
        v = -ceiling;
    }

    // Secondary safety clamp to 16-bit range to prevent integer overflow
    if (v > 32767.0f) {
        v = 32767.0f;
    } else if (v < -32768.0f) {
        v = -32768.0f;
    }

    int16_t out = (int16_t)roundf(v);
    int32_t mag = out < 0 ? -(int32_t)out : (int32_t)out;
    if (mag > lim->peak_output) {
        lim->peak_output = mag;
    }
    return out;
}

void audio_limiter_process_stereo(audio_limiter_t *lim, const int16_t *in_mono, int16_t *out_stereo, size_t count)
{
    if (!in_mono || !out_stereo) {
        return;
    }
    for (size_t i = 0; i < count; i++) {
        int16_t s = audio_limiter_process_sample(lim, in_mono[i]);
        out_stereo[2 * i] = s;
        out_stereo[2 * i + 1] = s;
    }
}

void audio_limiter_process_mono(audio_limiter_t *lim, const int16_t *in_mono, int16_t *out_mono, size_t count)
{
    if (!in_mono || !out_mono) {
        return;
    }
    for (size_t i = 0; i < count; i++) {
        out_mono[i] = audio_limiter_process_sample(lim, in_mono[i]);
    }
}
