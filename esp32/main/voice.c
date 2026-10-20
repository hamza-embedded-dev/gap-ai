#include "voice.h"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "api.h"
#include "audio_play.h"
#include "audio_record.h"
#include "board_pins.h"
#include "cJSON.h"
#include "display.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "secrets.h"

#define VOICE_HTTP_TIMEOUT_MS 30000 // STT + LLM + TTS round trip
#define MIN_HOLD_MS           400   // shorter presses are treated as accidental
#define BOUNDARY              "----gapai7d1f3b9c"
#define RX_BUF_BYTES          4096
#define JSON_BODY_MAX         4096

typedef struct {
    char content_type[48];
    char transcript[256];
    char reply[512];
    char intent[24];
} reply_headers_t;

#if BOARD_HAS_VOICE_HW

static const char *TAG = "voice";

esp_err_t voice_init(void)
{
    gpio_config_t btn = {
        .pin_bit_mask = 1ULL << PIN_BTN_RECORD,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    esp_err_t err = gpio_config(&btn);
    if (err == ESP_OK) {
        err = audio_play_init();
    }
    // The mic channel is created once and kept, so the speaker always gets the other
    // I2S port. Re-creating RX right after the speaker released the same port made
    // the first reads time out.
    audio_record_cfg_t mic = {
        .bclk_io_num = PIN_MIC_SCK,
        .ws_io_num = PIN_MIC_WS,
        .din_io_num = PIN_MIC_SD,
        .slot_mask = I2S_STD_SLOT_LEFT, // INMP441 L/R -> GND
    };
    if (err == ESP_OK) {
        err = audio_record_init(&mic);
    }
#if CONFIG_ESP_CONSOLE_UART
    // RX buffer for the console UART so keystrokes from `idf.py monitor` can be read.
    if (err == ESP_OK && !uart_is_driver_installed(CONFIG_ESP_CONSOLE_UART_NUM)) {
        err = uart_driver_install(CONFIG_ESP_CONSOLE_UART_NUM, 256, 0, 0, NULL, 0);
    }
#endif
    ESP_LOGI(TAG, "Ready: press Enter in the serial monitor (or hold the button) to talk");
    return err;
}

bool voice_button_pressed(void)
{
    return gpio_get_level(PIN_BTN_RECORD) == 0;
}

bool voice_serial_key(void)
{
#if CONFIG_ESP_CONSOLE_UART
    bool hit = false;
    uint8_t c;
    while (uart_read_bytes(CONFIG_ESP_CONSOLE_UART_NUM, &c, 1, 0) == 1) {
        hit |= c == '\r' || c == '\n' || c == ' ';
    }
    if (hit) {
        vTaskDelay(pdMS_TO_TICKS(50)); // swallow the LF of a CR LF pair
        uart_flush_input(CONFIG_ESP_CONSOLE_UART_NUM);
    }
    return hit;
#else
    return false;
#endif
}

static void beep(float hz, int ms)
{
    if (audio_play_begin(16000) != ESP_OK) {
        return;
    }
    int16_t buf[160];
    int total = 16 * ms;
    for (int done = 0; done < total; done += 160) {
        for (int i = 0; i < 160; i++) {
            buf[i] = (int16_t)(sinf(2.0f * (float)M_PI * hz * (done + i) / 16000.0f) * 12000.0f);
        }
        audio_play_write(buf, 160);
    }
    audio_play_end();
}

// Shows a short message (wrapped) under a title.
static void show_text(const char *title, const char *text)
{
    char lines[3][DISPLAY_LINE_BYTES] = {{0}};
    display_wrap(text, lines, 3);
    display_show(title, lines[0], lines[1], lines[2]);
}

static void url_decode(char *dst, size_t dst_size, const char *src)
{
    size_t o = 0;
    for (size_t i = 0; src[i] && o + 1 < dst_size; i++) {
        if (src[i] == '%' && isxdigit((unsigned char)src[i + 1]) && isxdigit((unsigned char)src[i + 2])) {
            char hex[3] = {src[i + 1], src[i + 2], 0};
            dst[o++] = (char)strtol(hex, NULL, 16);
            i += 2;
        } else {
            dst[o++] = src[i] == '+' ? ' ' : src[i];
        }
    }
    dst[o] = '\0';
}

static esp_err_t on_http_event(esp_http_client_event_t *evt)
{
    reply_headers_t *h = evt->user_data;
    if (evt->event_id != HTTP_EVENT_ON_HEADER || h == NULL) {
        return ESP_OK;
    }
    if (strcasecmp(evt->header_key, "Content-Type") == 0) {
        strlcpy(h->content_type, evt->header_value, sizeof(h->content_type));
    } else if (strcasecmp(evt->header_key, "X-Transcript") == 0) {
        url_decode(h->transcript, sizeof(h->transcript), evt->header_value);
    } else if (strcasecmp(evt->header_key, "X-Reply-Text") == 0) {
        url_decode(h->reply, sizeof(h->reply), evt->header_value);
    } else if (strcasecmp(evt->header_key, "X-Intent") == 0) {
        strlcpy(h->intent, evt->header_value, sizeof(h->intent));
    }
    return ESP_OK;
}

static bool write_all(esp_http_client_handle_t client, const uint8_t *data, size_t len)
{
    while (len > 0) {
        int n = esp_http_client_write(client, (const char *)data, len > 4096 ? 4096 : (int)len);
        if (n <= 0) {
            return false;
        }
        data += n;
        len -= n;
    }
    return true;
}

static uint32_t le32(const uint8_t *p)
{
    return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint16_t le16(const uint8_t *p)
{
    return p[0] | (p[1] << 8);
}

// Streams a WAV response body to the speaker. Parses the RIFF header from the first
// bytes, then plays the data chunk until the connection ends (TTS servers may send
// a streaming header with an unknown data size, so the size field is not trusted).
static esp_err_t play_wav_stream(esp_http_client_handle_t client)
{
    static uint8_t buf[RX_BUF_BYTES];
    int have = 0;
    int data_start = -1;
    uint16_t channels = 0, bits = 0;
    uint32_t rate = 0;

    while (data_start < 0) {
        int n = esp_http_client_read(client, (char *)buf + have, sizeof(buf) - have);
        if (n <= 0) {
            ESP_LOGE(TAG, "WAV ended before the data chunk (%d bytes)", have);
            return ESP_FAIL;
        }
        have += n;
        if (have < 12) {
            continue;
        }
        if (memcmp(buf, "RIFF", 4) != 0 || memcmp(buf + 8, "WAVE", 4) != 0) {
            ESP_LOGE(TAG, "Response is not a RIFF/WAVE file");
            return ESP_FAIL;
        }
        int pos = 12;
        while (pos + 8 <= have) {
            uint32_t size = le32(buf + pos + 4);
            if (memcmp(buf + pos, "fmt ", 4) == 0 && pos + 8 + 16 <= have) {
                channels = le16(buf + pos + 10);
                rate = le32(buf + pos + 12);
                bits = le16(buf + pos + 22);
            }
            if (memcmp(buf + pos, "data", 4) == 0) {
                data_start = pos + 8;
                break;
            }
            pos += 8 + (int)size + (int)(size & 1);
        }
        if (data_start < 0 && have == (int)sizeof(buf)) {
            ESP_LOGE(TAG, "No data chunk in the first %d bytes", have);
            return ESP_FAIL;
        }
    }

    if (bits != 16 || channels < 1 || channels > 2 || rate < 8000 || rate > 48000) {
        ESP_LOGE(TAG, "Unsupported WAV: %u ch, %u bit, %u Hz", channels, bits, (unsigned)rate);
        return ESP_ERR_NOT_SUPPORTED;
    }
    ESP_LOGI(TAG, "Playing reply: %u Hz, %u ch", (unsigned)rate, channels);
    esp_err_t err = audio_play_begin(rate);
    if (err != ESP_OK) {
        return err;
    }

    // Convert interleaved frames to mono; keep a partial frame across reads.
    const int frame_bytes = 2 * channels;
    static int16_t mono[RX_BUF_BYTES / 2]; // static: too big for the main task stack
    int off = data_start;
    size_t played = 0;
    while (true) {
        int frames = (have - off) / frame_bytes;
        for (int f = 0; f < frames; f++) {
            const uint8_t *p = buf + off + f * frame_bytes;
            int32_t s = (int16_t)le16(p);
            if (channels == 2) {
                s = (s + (int16_t)le16(p + 2)) / 2;
            }
            mono[f] = (int16_t)s;
        }
        audio_play_write(mono, frames);
        played += frames;
        off += frames * frame_bytes;

        int rest = have - off;
        memmove(buf, buf + off, rest);
        have = rest;
        off = 0;
        int n = esp_http_client_read(client, (char *)buf + have, sizeof(buf) - have);
        if (n <= 0) {
            break;
        }
        have += n;
    }
    audio_play_end();
    ESP_LOGI(TAG, "Reply played: %.1f s", (double)played / rate);
    return ESP_OK;
}

static void read_json_reply(esp_http_client_handle_t client, reply_headers_t *h)
{
    char *body = calloc(1, JSON_BODY_MAX + 1);
    if (body == NULL) {
        return;
    }
    int len = esp_http_client_read_response(client, body, JSON_BODY_MAX);
    cJSON *root = len > 0 ? cJSON_Parse(body) : NULL;
    const cJSON *reply = cJSON_GetObjectItemCaseSensitive(root, "reply_text");
    const cJSON *transcript = cJSON_GetObjectItemCaseSensitive(root, "transcript");
    const cJSON *message = cJSON_GetObjectItemCaseSensitive(root, "message"); // APIError body
    if (cJSON_IsString(reply)) {
        strlcpy(h->reply, reply->valuestring, sizeof(h->reply));
    } else if (cJSON_IsString(message)) {
        strlcpy(h->reply, message->valuestring, sizeof(h->reply));
    }
    if (cJSON_IsString(transcript)) {
        strlcpy(h->transcript, transcript->valuestring, sizeof(h->transcript));
    }
    if (root == NULL && len > 0) {
        ESP_LOGW(TAG, "Unparsed body: %.200s", body);
    }
    cJSON_Delete(root);
    free(body);
}

// Sends the WAV to POST /voice and plays/shows the answer.
static void send_and_reply(const uint8_t *wav, size_t wav_len)
{
    static const char head[] =
        "--" BOUNDARY "\r\n"
        "Content-Disposition: form-data; name=\"audio\"; filename=\"voice.wav\"\r\n"
        "Content-Type: audio/wav\r\n\r\n";
    static const char tail[] = "\r\n--" BOUNDARY "--\r\n";

    reply_headers_t h = {0};
    esp_http_client_config_t cfg;
    api_client_config(&cfg, BACKEND_BASE_URL "/voice");
    cfg.method = HTTP_METHOD_POST;
    cfg.timeout_ms = VOICE_HTTP_TIMEOUT_MS;
    cfg.buffer_size = 2048; // URL-encoded Turkish reply headers can be several hundred bytes
    cfg.buffer_size_tx = 1024;
    cfg.event_handler = on_http_event;
    cfg.user_data = &h;

    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == NULL) {
        show_text("Hata", "HTTP istemcisi yok");
        return;
    }
    esp_http_client_set_header(client, "Authorization", "Bearer " DEVICE_TOKEN);
    esp_http_client_set_header(client, "Content-Type", "multipart/form-data; boundary=" BOUNDARY);
    esp_http_client_set_header(client, "Accept", "audio/wav, application/json");

    display_show("Gonderiliyor...", NULL, NULL, NULL);
    int64_t t0 = esp_timer_get_time();
    size_t total = strlen(head) + wav_len + strlen(tail);
    esp_err_t err = esp_http_client_open(client, total);
    bool sent = err == ESP_OK && write_all(client, (const uint8_t *)head, strlen(head)) &&
                write_all(client, wav, wav_len) && write_all(client, (const uint8_t *)tail, strlen(tail));
    if (!sent) {
        ESP_LOGE(TAG, "Upload to /voice failed: %s", esp_err_to_name(err));
        show_text("Baglanti hatasi", "Backend'e ulasilamadi");
        esp_http_client_cleanup(client);
        return;
    }

    display_show("Dusunuyorum...", NULL, NULL, NULL);
    esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);
    ESP_LOGI(TAG, "POST /voice -> HTTP %d (%s) in %lld ms", status, h.content_type,
             (esp_timer_get_time() - t0) / 1000);

    bool is_wav = strncmp(h.content_type, "audio/wav", 9) == 0;
    if ((status == 200 || status == 201) && is_wav) {
        ESP_LOGI(TAG, "Transcript: %s | Reply: %s", h.transcript, h.reply);
        show_text("GAP:", h.reply);
        if (play_wav_stream(client) != ESP_OK) {
            show_text("GAP: (ses yok)", h.reply);
        }
    } else {
        read_json_reply(client, &h);
        ESP_LOGI(TAG, "Transcript: %s | Reply: %s", h.transcript, h.reply);
        if (status == 200 || status == 201) {
            show_text("GAP:", h.reply); // TTS off or failed: text only
        } else if (status == 401) {
            show_text("Yetki hatasi", "DEVICE_TOKEN gecersiz");
        } else {
            char title[24];
            snprintf(title, sizeof(title), "Hata HTTP %d", status);
            show_text(title, h.reply[0] ? h.reply : "Sunucu hatasi");
        }
    }

    esp_http_client_close(client);
    esp_http_client_cleanup(client);
}

void voice_run_turn(voice_trigger_t trigger)
{
    if (strlen(DEVICE_TOKEN) == 0) {
        show_text("Ayar eksik", "secrets.h: DEVICE_TOKEN");
        return;
    }

    beep(880, 80); // "listening" cue, finished before the mic starts

    if (audio_record_start(MAX_AUDIO_DURATION_SEC * 1000) != ESP_OK) {
        show_text("Hata", "Mikrofon baslatilamadi");
        return;
    }

    int64_t t0 = esp_timer_get_time();
    int shown = -1;
    const char *hint = trigger == VOICE_TRIGGER_SERIAL ? "Enter: gonder" : "Birakinca gonderir";
    ESP_LOGI(TAG, "Recording... %s", trigger == VOICE_TRIGGER_SERIAL ? "press Enter to send" : "release to send");
    while (audio_record_is_recording()) {
        bool stop = trigger == VOICE_TRIGGER_SERIAL ? voice_serial_key() : !voice_button_pressed();
        if (stop) {
            break;
        }
        int left = MAX_AUDIO_DURATION_SEC - (int)((esp_timer_get_time() - t0) / 1000000);
        if (left != shown) {
            char line[24];
            snprintf(line, sizeof(line), "%d sn kaldi", left);
            display_show("Dinliyorum...", line, NULL, hint);
            shown = left;
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    int held_ms = (int)((esp_timer_get_time() - t0) / 1000);

    uint8_t *wav = NULL;
    size_t wav_len = 0;
    esp_err_t err = audio_record_stop(&wav, &wav_len);
    if (err != ESP_OK || wav == NULL) {
        show_text("Hata", "Kayit alinamadi");
        audio_record_free_buffer(wav);
        return;
    }
    if (trigger == VOICE_TRIGGER_BUTTON && held_ms < MIN_HOLD_MS) {
        audio_record_free_buffer(wav);
        show_text("Konusmak icin", "butonu basili tut");
        return;
    }

    ESP_LOGI(TAG, "Recorded %u bytes (%d ms)", (unsigned)wav_len, held_ms);
    send_and_reply(wav, wav_len);
    audio_record_free_buffer(wav);
}

#else

esp_err_t voice_init(void)
{
    return ESP_ERR_NOT_SUPPORTED;
}

bool voice_button_pressed(void)
{
    return false;
}

bool voice_serial_key(void)
{
    return false;
}

void voice_run_turn(voice_trigger_t trigger)
{
}

#endif
