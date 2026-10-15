#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "driver/i2s_std.h"
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

// Canonical audio parameters according to GAP-AI architecture & API contract.
#define AUDIO_SAMPLE_RATE_HZ     16000
#define AUDIO_BITS_PER_SAMPLE    16
#define AUDIO_NUM_CHANNELS       1
#define AUDIO_BYTES_PER_SAMPLE   (AUDIO_BITS_PER_SAMPLE / 8)
#define AUDIO_BYTE_RATE          (AUDIO_SAMPLE_RATE_HZ * AUDIO_NUM_CHANNELS * AUDIO_BYTES_PER_SAMPLE) // 32000 B/s
#define MAX_AUDIO_DURATION_SEC   10
#define MAX_AUDIO_PCM_BYTES      (MAX_AUDIO_DURATION_SEC * AUDIO_BYTE_RATE)                          // 320000 B
#define MAX_AUDIO_WAV_BYTES      (44 + MAX_AUDIO_PCM_BYTES)                                          // 320044 B

/**
 * Standard 44-byte RIFF/WAVE header for mono 16-bit PCM.
 * Packed tightly to guarantee exact byte alignment on wire/file.
 */
#pragma pack(push, 1)
typedef struct {
    char     riff_tag[4];         // "RIFF"
    uint32_t riff_size;           // 36 + data_size
    char     wave_tag[4];         // "WAVE"
    char     fmt_tag[4];          // "fmt "
    uint32_t fmt_size;            // 16 for standard PCM
    uint16_t audio_format;        // 1 = PCM
    uint16_t num_channels;        // 1 = Mono
    uint32_t sample_rate;         // 16000 Hz
    uint32_t byte_rate;           // 32000 B/s (sample_rate * num_channels * bits_per_sample / 8)
    uint16_t block_align;         // 2 B (num_channels * bits_per_sample / 8)
    uint16_t bits_per_sample;     // 16 bit
    char     data_tag[4];         // "data"
    uint32_t data_size;           // Raw PCM byte count
} wav_header_t;
#pragma pack(pop)

// Compile-time assertion: header must be exactly 44 bytes with no compiler padding.
_Static_assert(sizeof(wav_header_t) == 44, "wav_header_t must be exactly 44 bytes");

/**
 * Hardware configuration for the I2S microphone (INMP441).
 * GPIO numbers must be explicitly provided by the caller; no default pins are assumed.
 */
typedef struct {
    int bclk_io_num;                // INMP441 SCK (Bit Clock) GPIO
    int ws_io_num;                  // INMP441 WS (Word Select / LRCLK) GPIO
    int din_io_num;                 // INMP441 SD (Serial Data Out) GPIO
    i2s_std_slot_mask_t slot_mask;  // Channel slot: I2S_STD_SLOT_LEFT (L/R -> GND) or I2S_STD_SLOT_RIGHT (L/R -> VDD)
} audio_record_cfg_t;

/**
 * Initialize I2S RX channel with the given pin configuration and 16 kHz std mode.
 * Does not start recording or allocate memory for audio.
 */
esp_err_t audio_record_init(const audio_record_cfg_t *cfg);

/**
 * Start an asynchronous audio recording session for up to max_duration_ms.
 * Checks available heap memory and allocates the required buffer.
 * If insufficient contiguous RAM exists, returns ESP_ERR_NO_MEM without crashing.
 *
 * @param max_duration_ms Maximum recording duration in milliseconds (max 10000).
 * @return ESP_OK on success, ESP_ERR_NO_MEM if memory cannot be allocated,
 *         or other error codes if I2S cannot be started.
 */
esp_err_t audio_record_start(uint32_t max_duration_ms);

/**
 * Stop active recording (or finalize a completed one), generate the 44-byte WAV header,
 * and transfer ownership of the allocated buffer to the caller.
 *
 * @param[out] out_wav_buffer Pointer to receive the allocated WAV buffer.
 * @param[out] out_wav_size   Pointer to receive total WAV size (44 + PCM bytes).
 * @return ESP_OK on success, ESP_ERR_INVALID_STATE if not recording / no buffer available.
 */
esp_err_t audio_record_stop(uint8_t **out_wav_buffer, size_t *out_wav_size);

/**
 * Free a buffer returned by audio_record_stop().
 */
void audio_record_free_buffer(uint8_t *wav_buffer);

/**
 * Check if recording is currently in progress.
 */
bool audio_record_is_recording(void);

/**
 * Deinitialize I2S channel and free all internal resources.
 */
void audio_record_deinit(void);

#ifdef __cplusplus
}
#endif
