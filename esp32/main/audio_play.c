#include "audio_play.h"

#include <math.h>

#include "board_pins.h"
#include "esp_log.h"

#if BOARD_HAS_VOICE_HW

#include "driver/gpio.h"
#include "driver/i2s_std.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define HIGH_PASS_HZ 250.0f
#define FADE_IN_MS   10
#define CHUNK_FRAMES 256

static const char *TAG = "audio_play";

static i2s_chan_handle_t s_tx;
static uint32_t s_rate;
static float s_hp_alpha, s_hp_prev_in, s_hp_prev_out;
static uint32_t s_fade_total, s_fade_done;

esp_err_t audio_play_init(void)
{
    gpio_reset_pin(PIN_AMP_SD);
    gpio_set_direction(PIN_AMP_SD, GPIO_MODE_OUTPUT);
    return gpio_set_level(PIN_AMP_SD, 0);
}

static void write_silence(uint32_t frames)
{
    static const int16_t zero[CHUNK_FRAMES * 2];
    while (frames > 0) {
        uint32_t n = frames < CHUNK_FRAMES ? frames : CHUNK_FRAMES;
        size_t written;
        i2s_channel_write(s_tx, zero, n * 4, &written, portMAX_DELAY);
        frames -= n;
    }
}

esp_err_t audio_play_begin(uint32_t sample_rate)
{
    if (s_tx != NULL) {
        return ESP_ERR_INVALID_STATE;
    }
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO, I2S_ROLE_MASTER);
    chan_cfg.auto_clear = true; // underrun plays silence instead of repeating old audio
    esp_err_t err = i2s_new_channel(&chan_cfg, &s_tx, NULL);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_new_channel failed: %s", esp_err_to_name(err));
        return err;
    }

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(sample_rate),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = PIN_AMP_BCLK,
            .ws = PIN_AMP_LRC,
            .dout = PIN_AMP_DIN,
            .din = I2S_GPIO_UNUSED,
        },
    };
    err = i2s_channel_init_std_mode(s_tx, &std_cfg);
    if (err == ESP_OK) {
        err = i2s_channel_enable(s_tx);
    }
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2S TX setup at %u Hz failed: %s", (unsigned)sample_rate, esp_err_to_name(err));
        i2s_del_channel(s_tx);
        s_tx = NULL;
        return err;
    }

    s_rate = sample_rate;
    float rc = 1.0f / (2.0f * (float)M_PI * HIGH_PASS_HZ);
    float dt = 1.0f / (float)sample_rate;
    s_hp_alpha = rc / (rc + dt);
    s_hp_prev_in = s_hp_prev_out = 0;
    s_fade_total = sample_rate * FADE_IN_MS / 1000;
    s_fade_done = 0;

    write_silence(sample_rate / 50); // clocks running before the amp wakes up
    gpio_set_level(PIN_AMP_SD, 1);
    return ESP_OK;
}

esp_err_t audio_play_write(const int16_t *samples, size_t count)
{
    if (s_tx == NULL) {
        return ESP_ERR_INVALID_STATE;
    }
    static int16_t out[CHUNK_FRAMES * 2]; // static: keeps the caller's stack small
    while (count > 0) {
        size_t n = count < CHUNK_FRAMES ? count : CHUNK_FRAMES;
        for (size_t i = 0; i < n; i++) {
            float x = samples[i];
            float y = s_hp_alpha * (s_hp_prev_out + x - s_hp_prev_in);
            s_hp_prev_in = x;
            s_hp_prev_out = y;

            float gain = AUDIO_PLAY_VOLUME;
            if (s_fade_done < s_fade_total) {
                gain *= (float)s_fade_done++ / (float)s_fade_total;
            }
            float v = y * gain;
            v = v > 32767.0f ? 32767.0f : v < -32768.0f ? -32768.0f : v;
            out[2 * i] = out[2 * i + 1] = (int16_t)v; // same sample in both slots
        }
        size_t written;
        esp_err_t err = i2s_channel_write(s_tx, out, n * 4, &written, portMAX_DELAY);
        if (err != ESP_OK) {
            return err;
        }
        samples += n;
        count -= n;
    }
    return ESP_OK;
}

void audio_play_end(void)
{
    if (s_tx == NULL) {
        return;
    }
    // Push enough silence through to flush the DMA queue before muting.
    write_silence(s_rate / 10);
    gpio_set_level(PIN_AMP_SD, 0);
    i2s_channel_disable(s_tx);
    i2s_del_channel(s_tx);
    s_tx = NULL;
}

#else

esp_err_t audio_play_init(void)
{
    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t audio_play_begin(uint32_t sample_rate)
{
    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t audio_play_write(const int16_t *samples, size_t count)
{
    return ESP_ERR_NOT_SUPPORTED;
}

void audio_play_end(void)
{
}

#endif
