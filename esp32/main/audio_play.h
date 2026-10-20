#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

// Output level cap as a fraction of digital full scale. With the MAX98357A at its
// default 9 dB gain, full scale is ~1.6 W into 8 ohm, so 0.5 keeps a continuous
// tone at ~0.4 W for the 0.5 W speaker. Do not raise it without lowering GAIN.
#define AUDIO_PLAY_VOLUME 0.50f

// Puts the amplifier into shutdown (SD low). Call once at boot.
esp_err_t audio_play_init(void);

// Opens an I2S output at sample_rate (mono 16-bit samples) and un-mutes the amp.
// The I2S port is only held between begin and end, so chips with a single I2S
// port can still record in between.
esp_err_t audio_play_begin(uint32_t sample_rate);

// Plays mono 16-bit PCM. Applies the volume cap, a ~250 Hz high-pass (the small
// speaker cannot reproduce bass) and a short fade-in to avoid a pop.
esp_err_t audio_play_write(const int16_t *samples, size_t count);

// Drains the output, mutes the amp and releases the I2S port.
void audio_play_end(void);
