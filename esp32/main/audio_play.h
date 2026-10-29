#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

// Speaker hardware rating: 0.5 W, 8 Ohm.
// The MAX98357A Class D amplifier with 5V VIN and 9 dB gain can exceed 0.5 W into 8 Ohm
// on sustained or high-level full scale signals.
// AUDIO_PLAY_VOLUME (default 0.35f) provides conservative digital attenuation.
// NOTE: Digital scaling is a starting attenuation value, NOT a guaranteed 0.5 W electrical
// limit. Physical output wattage depends on supply voltage, hardware gain pin configuration,
// speaker load impedance, and audio crest factor, and requires bench measurement to verify.
#include "audio_limiter.h"

#define AUDIO_PLAY_VOLUME AUDIO_LIMITER_DEFAULT_SCALE

// Puts the amplifier into shutdown (SD low). Call once at boot.
esp_err_t audio_play_init(void);

// Opens an I2S output at sample_rate (mono 16-bit samples) and un-mutes the amp.
// The I2S port is only held between begin and end, so chips with a single I2S
// port can still record in between.
esp_err_t audio_play_begin(uint32_t sample_rate);

// Plays mono 16-bit PCM. Applies the configurable volume limiter, high-pass filter
// (~250 Hz cutoff for speaker voice-coil protection), and a short fade-in to prevent pops.
esp_err_t audio_play_write(const int16_t *samples, size_t count);

// Drains the output, mutes the amp and releases the I2S port.
void audio_play_end(void);

// Configurable digital volume limiter functions
float audio_play_get_volume_limit(void);
void audio_play_set_volume_limit(float limit);

// Configurable high-pass filter cutoff in Hz (default 80.0 Hz; <= 0 disables HPF)
void audio_play_set_high_pass(float hp_hz);
float audio_play_get_high_pass(void);

// Playback diagnostics and underrun tracking
typedef struct {
    uint32_t total_frames_written;
    uint32_t total_bytes_sent;
    uint32_t write_errors;
    uint32_t underrun_count;
    int32_t peak_amplitude;
    uint32_t sample_rate;
} audio_play_stats_t;

audio_play_stats_t audio_play_get_stats(void);
void audio_play_reset_stats(void);
