#include "audio_record.h"

#include <string.h>

#include "esp_check.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

static const char *TAG = "audio_rec";

#define I2S_READ_CHUNK_SAMPLES  128
#define I2S_READ_TIMEOUT_MS     200
#define TASK_STACK_SIZE         4096
#define TASK_PRIORITY           5
#define TASK_STOP_TIMEOUT_MS    1500
#define API_MUTEX_TIMEOUT_MS    1000

// Internal synchronization and state
static i2s_chan_handle_t        s_rx_chan = NULL;
static bool                     s_initialized = false;
static volatile bool            s_recording = false;
static volatile bool            s_stop_requested = false;
static TaskHandle_t             s_task_handle = NULL;
static SemaphoreHandle_t        s_done_sem = NULL;
static SemaphoreHandle_t        s_lock = NULL;

static uint8_t                 *s_wav_buffer = NULL;
static size_t                   s_target_pcm_bytes = 0;
static size_t                   s_current_pcm_bytes = 0;
static esp_err_t                s_last_error = ESP_OK;

static void build_wav_header(wav_header_t *header, uint32_t pcm_data_bytes)
{
    memcpy(header->riff_tag, "RIFF", 4);
    header->riff_size = 36 + pcm_data_bytes;
    memcpy(header->wave_tag, "WAVE", 4);

    memcpy(header->fmt_tag, "fmt ", 4);
    header->fmt_size = 16;
    header->audio_format = 1; // PCM
    header->num_channels = AUDIO_NUM_CHANNELS;
    header->sample_rate = AUDIO_SAMPLE_RATE_HZ;
    header->byte_rate = AUDIO_BYTE_RATE;
    header->block_align = (uint16_t)(AUDIO_NUM_CHANNELS * AUDIO_BYTES_PER_SAMPLE);
    header->bits_per_sample = AUDIO_BITS_PER_SAMPLE;

    memcpy(header->data_tag, "data", 4);
    header->data_size = pcm_data_bytes;
}

static void audio_record_task(void *arg)
{
    ESP_LOGI(TAG, "Recording task started, target PCM bytes: %u", (unsigned)s_target_pcm_bytes);

    int32_t raw_samples[I2S_READ_CHUNK_SAMPLES];
    uint8_t *pcm_dest = s_wav_buffer + sizeof(wav_header_t);

    while (!s_stop_requested && s_current_pcm_bytes < s_target_pcm_bytes) {
        size_t bytes_read = 0;
        // The timeout argument is in milliseconds (not ticks): pdMS_TO_TICKS(200) gave
        // 20 ms at 100 Hz, shorter than one DMA buffer, and ended recordings early.
        esp_err_t err = i2s_channel_read(s_rx_chan, raw_samples, sizeof(raw_samples),
                                         &bytes_read, I2S_READ_TIMEOUT_MS);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "i2s_channel_read returned %s", esp_err_to_name(err));
            s_last_error = err;
            break;
        }

        size_t samples_read = bytes_read / sizeof(int32_t);
        for (size_t i = 0; i < samples_read; i++) {
            if (s_current_pcm_bytes + sizeof(int16_t) > s_target_pcm_bytes) {
                break;
            }

            // INMP441 outputs 24-bit audio in a 32-bit slot, MSB aligned.
            // Bit 31 is the sign bit. An arithmetic right shift preserves sign
            // extension. >> 16 would keep the top 16 bits, but normal speech then
            // peaks around -28 dBFS; AUDIO_RECORD_SHIFT 14 is 4x (+12 dB) louder,
            // with clipping instead of wrap-around on very loud input.
            int32_t scaled = raw_samples[i] >> AUDIO_RECORD_SHIFT;
            if (scaled > INT16_MAX) {
                scaled = INT16_MAX;
            } else if (scaled < INT16_MIN) {
                scaled = INT16_MIN;
            }
            int16_t pcm_sample = (int16_t)scaled;

            memcpy(pcm_dest + s_current_pcm_bytes, &pcm_sample, sizeof(int16_t));
            s_current_pcm_bytes += sizeof(int16_t);
        }
    }

    ESP_LOGI(TAG, "Recording task finished. Recorded PCM bytes: %u", (unsigned)s_current_pcm_bytes);

    // Stop I2S DMA reception first
    i2s_channel_disable(s_rx_chan);

    // Finalize header with actual recorded bytes
    if (s_wav_buffer != NULL) {
        build_wav_header((wav_header_t *)s_wav_buffer, (uint32_t)s_current_pcm_bytes);
    }

    s_recording = false;

    // Signal completion to waiting caller (stop or deinit)
    if (s_done_sem != NULL) {
        xSemaphoreGive(s_done_sem);
    }

    vTaskDelete(NULL);
}

esp_err_t audio_record_init(const audio_record_cfg_t *cfg)
{
    if (cfg == NULL) {
        ESP_LOGE(TAG, "audio_record_init: config pointer is NULL");
        return ESP_ERR_INVALID_ARG;
    }

    if (cfg->slot_mask != I2S_STD_SLOT_LEFT && cfg->slot_mask != I2S_STD_SLOT_RIGHT) {
        ESP_LOGE(TAG, "audio_record_init: invalid slot_mask 0x%x (must be I2S_STD_SLOT_LEFT or I2S_STD_SLOT_RIGHT)",
                 (unsigned)cfg->slot_mask);
        return ESP_ERR_INVALID_ARG;
    }

    if (s_initialized) {
        ESP_LOGW(TAG, "audio_record already initialized");
        return ESP_OK;
    }

    ESP_LOGI(TAG, "Initializing I2S standard RX: BCLK=%d, WS=%d, DIN=%d, slot_mask=0x%x",
             cfg->bclk_io_num, cfg->ws_io_num, cfg->din_io_num, (unsigned)cfg->slot_mask);

    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    esp_err_t err = i2s_new_channel(&chan_cfg, NULL, &s_rx_chan);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_new_channel failed: %s", esp_err_to_name(err));
        return err;
    }

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(AUDIO_SAMPLE_RATE_HZ),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = cfg->bclk_io_num,
            .ws = cfg->ws_io_num,
            .dout = I2S_GPIO_UNUSED,
            .din = cfg->din_io_num,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };
    std_cfg.slot_cfg.slot_mask = cfg->slot_mask;

    err = i2s_channel_init_std_mode(s_rx_chan, &std_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_channel_init_std_mode failed: %s", esp_err_to_name(err));
        i2s_del_channel(s_rx_chan);
        s_rx_chan = NULL;
        return err;
    }

    s_done_sem = xSemaphoreCreateBinary();
    if (s_done_sem == NULL) {
        i2s_del_channel(s_rx_chan);
        s_rx_chan = NULL;
        return ESP_ERR_NO_MEM;
    }

    s_lock = xSemaphoreCreateMutex();
    if (s_lock == NULL) {
        vSemaphoreDelete(s_done_sem);
        s_done_sem = NULL;
        i2s_del_channel(s_rx_chan);
        s_rx_chan = NULL;
        return ESP_ERR_NO_MEM;
    }

    s_task_handle = NULL;
    s_wav_buffer = NULL;
    s_recording = false;
    s_stop_requested = false;
    s_initialized = true;
    return ESP_OK;
}

esp_err_t audio_record_start(uint32_t max_duration_ms)
{
    if (!s_initialized) {
        ESP_LOGE(TAG, "audio_record_start: module not initialized");
        return ESP_ERR_INVALID_STATE;
    }

    if (xSemaphoreTake(s_lock, pdMS_TO_TICKS(API_MUTEX_TIMEOUT_MS)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }

    if (s_task_handle != NULL || s_recording) {
        ESP_LOGW(TAG, "Recording already in progress or task still running");
        xSemaphoreGive(s_lock);
        return ESP_ERR_INVALID_STATE;
    }

    // Free any unretrieved previous buffer
    if (s_wav_buffer != NULL) {
        free(s_wav_buffer);
        s_wav_buffer = NULL;
    }

    if (max_duration_ms == 0) {
        max_duration_ms = MAX_AUDIO_DURATION_SEC * 1000;
    } else if (max_duration_ms > (MAX_AUDIO_DURATION_SEC * 1000)) {
        ESP_LOGW(TAG, "Duration %u ms exceeds MAX_AUDIO_DURATION_SEC (%d s), capping",
                 (unsigned)max_duration_ms, MAX_AUDIO_DURATION_SEC);
        max_duration_ms = MAX_AUDIO_DURATION_SEC * 1000;
    }

    size_t target_pcm = ((uint64_t)max_duration_ms * AUDIO_BYTE_RATE) / 1000;
    target_pcm &= ~1; // Ensure 16-bit sample alignment
    size_t total_wav_bytes = sizeof(wav_header_t) + target_pcm;

    // Try external PSRAM first (SPIRAM), fall back to internal DRAM if PSRAM is absent.
    s_wav_buffer = (uint8_t *)heap_caps_malloc(total_wav_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (s_wav_buffer != NULL) {
        ESP_LOGI(TAG, "Allocated %u B WAV buffer in external PSRAM", (unsigned)total_wav_bytes);
    } else {
        size_t largest_free_dram = heap_caps_get_largest_free_block(MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL);
        if (largest_free_dram < total_wav_bytes) {
            ESP_LOGE(TAG, "Cannot allocate %u B WAV buffer in internal DRAM (largest free block: %u B). "
                          "PSRAM not available or not configured.",
                     (unsigned)total_wav_bytes, (unsigned)largest_free_dram);
            xSemaphoreGive(s_lock);
            return ESP_ERR_NO_MEM;
        }

        s_wav_buffer = (uint8_t *)malloc(total_wav_bytes);
        if (s_wav_buffer == NULL) {
            ESP_LOGE(TAG, "malloc failed for %u B", (unsigned)total_wav_bytes);
            xSemaphoreGive(s_lock);
            return ESP_ERR_NO_MEM;
        }
        ESP_LOGI(TAG, "Allocated %u B WAV buffer in internal DRAM", (unsigned)total_wav_bytes);
    }

    s_target_pcm_bytes = target_pcm;
    s_current_pcm_bytes = 0;
    s_last_error = ESP_OK;
    s_stop_requested = false;
    s_recording = true;

    // Reset binary semaphore so it's guaranteed empty
    xSemaphoreTake(s_done_sem, 0);

    esp_err_t err = i2s_channel_enable(s_rx_chan);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_channel_enable failed: %s", esp_err_to_name(err));
        free(s_wav_buffer);
        s_wav_buffer = NULL;
        s_recording = false;
        xSemaphoreGive(s_lock);
        return err;
    }

    BaseType_t ret = xTaskCreate(audio_record_task, "audio_rec", TASK_STACK_SIZE,
                                 NULL, TASK_PRIORITY, &s_task_handle);
    if (ret != pdPASS) {
        ESP_LOGE(TAG, "Failed to create audio_record_task");
        i2s_channel_disable(s_rx_chan);
        free(s_wav_buffer);
        s_wav_buffer = NULL;
        s_recording = false;
        s_task_handle = NULL;
        xSemaphoreGive(s_lock);
        return ESP_ERR_NO_MEM;
    }

    xSemaphoreGive(s_lock);
    return ESP_OK;
}

esp_err_t audio_record_stop(uint8_t **out_wav_buffer, size_t *out_wav_size)
{
    if (out_wav_buffer == NULL || out_wav_size == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    // Default outputs to safe values initially
    *out_wav_buffer = NULL;
    *out_wav_size = 0;

    if (!s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }

    if (xSemaphoreTake(s_lock, pdMS_TO_TICKS(API_MUTEX_TIMEOUT_MS)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }

    // If task was created and has not been synchronized yet:
    if (s_task_handle != NULL) {
        s_stop_requested = true;
        // Wait for recording task to flush, disable I2S, and complete
        if (xSemaphoreTake(s_done_sem, pdMS_TO_TICKS(TASK_STOP_TIMEOUT_MS)) != pdTRUE) {
            ESP_LOGE(TAG, "Timeout waiting for recording task completion; buffer ownership retained internally");
            xSemaphoreGive(s_lock);
            return ESP_ERR_TIMEOUT;
        }
        // Task has completed, disabled I2S, finalized header, and signaled s_done_sem!
        s_task_handle = NULL;
    }

    if (s_wav_buffer == NULL) {
        ESP_LOGW(TAG, "No WAV buffer available to return");
        xSemaphoreGive(s_lock);
        return ESP_ERR_INVALID_STATE;
    }

    // Header was already finalized by task; re-verify consistency
    build_wav_header((wav_header_t *)s_wav_buffer, (uint32_t)s_current_pcm_bytes);

    *out_wav_buffer = s_wav_buffer;
    *out_wav_size = sizeof(wav_header_t) + s_current_pcm_bytes;

    // Transfer buffer ownership to caller
    s_wav_buffer = NULL;
    s_target_pcm_bytes = 0;
    s_current_pcm_bytes = 0;

    esp_err_t res = s_last_error;
    xSemaphoreGive(s_lock);
    return res;
}

void audio_record_free_buffer(uint8_t *wav_buffer)
{
    if (wav_buffer != NULL) {
        free(wav_buffer);
    }
}

bool audio_record_is_recording(void)
{
    return s_recording && (s_task_handle != NULL);
}

void audio_record_deinit(void)
{
    if (!s_initialized) {
        return;
    }

    if (s_lock != NULL) {
        if (xSemaphoreTake(s_lock, pdMS_TO_TICKS(API_MUTEX_TIMEOUT_MS)) != pdTRUE) {
            ESP_LOGE(TAG, "Cannot deinit: failed to acquire lock");
            return;
        }
    }

    if (s_task_handle != NULL) {
        s_stop_requested = true;
        if (xSemaphoreTake(s_done_sem, pdMS_TO_TICKS(TASK_STOP_TIMEOUT_MS)) != pdTRUE) {
            ESP_LOGE(TAG, "Cannot deinit cleanly: recording task did not exit within timeout");
            if (s_lock != NULL) {
                xSemaphoreGive(s_lock);
            }
            return;
        }
        s_task_handle = NULL;
    }

    if (s_wav_buffer != NULL) {
        free(s_wav_buffer);
        s_wav_buffer = NULL;
    }

    if (s_rx_chan != NULL) {
        i2s_channel_disable(s_rx_chan);
        i2s_del_channel(s_rx_chan);
        s_rx_chan = NULL;
    }

    if (s_done_sem != NULL) {
        vSemaphoreDelete(s_done_sem);
        s_done_sem = NULL;
    }

    s_target_pcm_bytes = 0;
    s_current_pcm_bytes = 0;
    s_recording = false;
    s_stop_requested = false;
    s_initialized = false;

    SemaphoreHandle_t lock_to_delete = s_lock;
    s_lock = NULL;
    if (lock_to_delete != NULL) {
        xSemaphoreGive(lock_to_delete);
        vSemaphoreDelete(lock_to_delete);
    }

    ESP_LOGI(TAG, "audio_record deinitialized");
}
