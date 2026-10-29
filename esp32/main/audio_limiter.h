#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

// Default conservative digital scale factor (0.35 = -9.1 dBFS).
// WARNING: This digital scaling factor is a conservative starting attenuation value,
// NOT a guaranteed 0.5 W electrical power limit. Actual output power delivered to the
// speaker depends on the MAX98357A amplifier supply voltage (e.g. 5V), hardware GAIN pin
// configuration, speaker load impedance (8 ohms), and the crest factor/frequency spectrum
// of the audio signal. Measuring output voltage with an oscilloscope or RMS voltmeter
// across the speaker terminals is required to confirm exact acoustic and electrical wattage.
#define AUDIO_LIMITER_DEFAULT_SCALE   0.35f
#define AUDIO_LIMITER_MIN_SCALE       0.0f
#define AUDIO_LIMITER_MAX_SCALE       1.0f

// High-pass filter for DC offset and sub-rumble suppression (< 80 Hz).
// Set to 80.0 Hz to preserve adult male (85-180 Hz) and female (165-255 Hz) vocal fundamentals,
// preventing thin/muffled speech while blocking inaudible table thumps and DC bias.
// NOTE: The high-pass filter is for voicing and acoustic cleanup, NOT physical power protection.
#define AUDIO_LIMITER_DEFAULT_HP_HZ   80.0f
#define AUDIO_LIMITER_DEFAULT_FADE_MS 10

typedef struct {
    float scale;              // Current volume limit scale [0.0 .. 1.0]
    float high_pass_hz;       // High-pass filter cutoff (default 80 Hz; <= 0 disables HPF)
    float hp_alpha;           // High-pass filter alpha coefficient
    float hp_prev_in;         // Previous input sample
    float hp_prev_out;        // Previous output sample
    uint32_t fade_total;      // Total frames for fade-in
    uint32_t fade_done;       // Frames faded so far
    uint32_t sample_rate;     // Sample rate in Hz
    int32_t peak_output;      // Diagnostic: maximum absolute output sample observed
} audio_limiter_t;

// Initialize the limiter state with given scale and sample rate.
void audio_limiter_init(audio_limiter_t *lim, float initial_scale, uint32_t sample_rate);

// Reset filter state and restart fade-in (e.g., when a new playback begins)
void audio_limiter_reset(audio_limiter_t *lim);

// Set digital scale factor (clamped safely between 0.0f and 1.0f)
void audio_limiter_set_scale(audio_limiter_t *lim, float scale);

// Get active digital scale factor
float audio_limiter_get_scale(const audio_limiter_t *lim);

// Configure high-pass filter cutoff in Hz (e.g. 80.0f). If hp_hz <= 0.0f, HPF is bypassed.
void audio_limiter_set_high_pass(audio_limiter_t *lim, float hp_hz);

// Get active high-pass filter cutoff in Hz
float audio_limiter_get_high_pass(const audio_limiter_t *lim);

// Process a single 16-bit mono PCM sample.
// Returns an int16_t that is guaranteed:
// 1. Scaled by the active limiter scale and fade-in
// 2. High-pass filtered (if hp_hz > 0) to suppress DC and sub-rumble
// 3. Strictly bounded to [-max_allowed, +max_allowed] where max_allowed = round(32767.0f * scale)
// 4. Immune to integer overflow on positive or negative full-scale inputs or filter overshoot
int16_t audio_limiter_process_sample(audio_limiter_t *lim, int16_t sample);

// Process a buffer of mono samples and output stereo interleaved samples (for I2S stereo slot)
// out_stereo must have space for at least 2 * count int16_t elements.
void audio_limiter_process_stereo(audio_limiter_t *lim, const int16_t *in_mono, int16_t *out_stereo, size_t count);

// Process a buffer of mono samples in-place or to another mono buffer
void audio_limiter_process_mono(audio_limiter_t *lim, const int16_t *in_mono, int16_t *out_mono, size_t count);

#ifdef __cplusplus
}
#endif
