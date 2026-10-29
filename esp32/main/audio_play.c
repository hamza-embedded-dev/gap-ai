#include "audio_play.h"

#include <math.h>

#include "board_pins.h"
#include "esp_log.h"

#if BOARD_HAS_VOICE_HW

#include "driver/gpio.h"
#include "driver/i2s_std.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_timer.h"

#define CHUNK_FRAMES 512

static const char *TAG = "audio_play";

static i2s_chan_handle_t s_tx;
static uint32_t s_rate;
static audio_limiter_t s_limiter;
static bool s_limiter_inited = false;
static audio_play_stats_t s_stats;
static int64_t s_last_write_us = 0;
static int64_t s_buffered_frames = 0;

esp_err_t audio_play_init(void)
{
    if (!s_limiter_inited) {
        audio_limiter_init(&s_limiter, AUDIO_LIMITER_DEFAULT_SCALE, 16000);
        s_limiter_inited = true;
    }
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
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    chan_cfg.auto_clear = true; // underrun plays silence instead of repeating old audio
    chan_cfg.dma_desc_num = 8;
    chan_cfg.dma_frame_num = 1024; // 8 * 1024 frames = ~341ms hardware FIFO buffer
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
    if (!s_limiter_inited) {
        audio_limiter_init(&s_limiter, AUDIO_LIMITER_DEFAULT_SCALE, sample_rate);
        s_limiter_inited = true;
    } else {
        float cur_scale = s_limiter.scale;
        float cur_hp = s_limiter.high_pass_hz;
        audio_limiter_init(&s_limiter, cur_scale, sample_rate);
        audio_limiter_set_high_pass(&s_limiter, cur_hp);
    }

    memset(&s_stats, 0, sizeof(s_stats));
    s_stats.sample_rate = sample_rate;
    s_last_write_us = 0;
    s_buffered_frames = 0;

    write_silence(sample_rate / 50); // clocks running before the amp wakes up
    gpio_set_level(PIN_AMP_SD, 1);
    return ESP_OK;
}

esp_err_t audio_play_write(const int16_t *samples, size_t count)
{
    if (s_tx == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    // Monitor DMA starvation / underrun intervals
    int64_t now_us = esp_timer_get_time();
    if (s_last_write_us > 0 && s_rate > 0) {
        int64_t elapsed_us = now_us - s_last_write_us;
        int64_t drained_frames = (elapsed_us * (int64_t)s_rate) / 1000000LL;
        if (drained_frames >= s_buffered_frames + (int64_t)(s_rate / 100)) { // > 10ms gap past buffer drain
            s_stats.underrun_count++;
            ESP_LOGW(TAG, "I2S DMA underrun: gap=%lld ms (drained=%lld frames, buffered=%lld)",
                     (elapsed_us - ((s_buffered_frames * 1000000LL) / s_rate)) / 1000LL,
                     drained_frames, s_buffered_frames);
            s_buffered_frames = 0;
        } else {
            s_buffered_frames -= drained_frames;
            if (s_buffered_frames < 0) s_buffered_frames = 0;
        }
    }
    s_last_write_us = now_us;
    s_buffered_frames += count;

    static int16_t out[CHUNK_FRAMES * 2]; // static: keeps the caller's stack small
    while (count > 0) {
        size_t n = count < CHUNK_FRAMES ? count : CHUNK_FRAMES;
        audio_limiter_process_stereo(&s_limiter, samples, out, n);
        size_t written = 0;
        esp_err_t err = i2s_channel_write(s_tx, out, n * 4, &written, portMAX_DELAY);
        if (err != ESP_OK || written != n * 4) {
            s_stats.write_errors++;
            ESP_LOGE(TAG, "i2s_channel_write failed: %s (written=%u/%u)",
                     esp_err_to_name(err), (unsigned)written, (unsigned)(n * 4));
            return err != ESP_OK ? err : ESP_FAIL;
        }
        s_stats.total_frames_written += n;
        s_stats.total_bytes_sent += written;
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

    ESP_LOGI(TAG, "Playback summary: %u frames (%u ms @ %u Hz), underruns=%u, write_errors=%u, peak=%d",
             (unsigned)s_stats.total_frames_written,
             (unsigned)(s_stats.total_frames_written * 1000ULL / (s_rate ? s_rate : 1)),
             (unsigned)s_rate,
             (unsigned)s_stats.underrun_count,
             (unsigned)s_stats.write_errors,
             (int)s_limiter.peak_output);
}

float audio_play_get_volume_limit(void)
{
    if (!s_limiter_inited) {
        audio_limiter_init(&s_limiter, AUDIO_LIMITER_DEFAULT_SCALE, 16000);
        s_limiter_inited = true;
    }
    return audio_limiter_get_scale(&s_limiter);
}

void audio_play_set_volume_limit(float limit)
{
    if (!s_limiter_inited) {
        audio_limiter_init(&s_limiter, AUDIO_LIMITER_DEFAULT_SCALE, 16000);
        s_limiter_inited = true;
    }
    audio_limiter_set_scale(&s_limiter, limit);
}

void audio_play_set_high_pass(float hp_hz)
{
    if (!s_limiter_inited) {
        audio_limiter_init(&s_limiter, AUDIO_LIMITER_DEFAULT_SCALE, 16000);
        s_limiter_inited = true;
    }
    audio_limiter_set_high_pass(&s_limiter, hp_hz);
}

float audio_play_get_high_pass(void)
{
    if (!s_limiter_inited) {
        audio_limiter_init(&s_limiter, AUDIO_LIMITER_DEFAULT_SCALE, 16000);
        s_limiter_inited = true;
    }
    return audio_limiter_get_high_pass(&s_limiter);
}

audio_play_stats_t audio_play_get_stats(void)
{
    s_stats.peak_amplitude = s_limiter.peak_output;
    return s_stats;
}

void audio_play_reset_stats(void)
{
    memset(&s_stats, 0, sizeof(s_stats));
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

float audio_play_get_volume_limit(void)
{
    return AUDIO_LIMITER_DEFAULT_SCALE;
}

void audio_play_set_volume_limit(float limit)
{
    (void)limit;
}

void audio_play_set_high_pass(float hp_hz)
{
    (void)hp_hz;
}

float audio_play_get_high_pass(void)
{
    return AUDIO_LIMITER_DEFAULT_HP_HZ;
}

audio_play_stats_t audio_play_get_stats(void)
{
    audio_play_stats_t dummy = {0};
    return dummy;
}

void audio_play_reset_stats(void)
{
}

#endif
