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
#include "discover.h"
#include "display.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "secrets.h"
#include "settings.h"

#define VOICE_HTTP_TIMEOUT_MS 60000 // STT + LLM (<=40s budget, backend) + TTS round trip
#define MIN_HOLD_MS           400   // shorter presses are treated as accidental
#define BOUNDARY              "----gapai7d1f3b9c"
#define RX_BUF_BYTES          4096
#define JSON_BODY_MAX         4096

typedef struct {
    char content_type[48];
    char transcript[256];
    char reply[512];
    char intent[32];
    bool needs_button;
    char proposal_id[48];
    char conversation_id[48];
} reply_headers_t;

#if BOARD_HAS_VOICE_HW

static const char *TAG = "voice";
static char s_active_proposal_id[48] = {0};
static char s_active_conversation_id[48] = {0};

bool voice_has_pending_proposal(void)
{
    return s_active_proposal_id[0] != '\0';
}

bool voice_has_pending_conversation(void)
{
    return s_active_conversation_id[0] != '\0';
}

const char *voice_get_active_conversation_id(void)
{
    return s_active_conversation_id;
}

void voice_clear_active_conversation(void)
{
    s_active_conversation_id[0] = '\0';
}

static gap_mode_t s_device_mode = GAP_MODE_PLAN;

gap_mode_t voice_get_mode(void)
{
    return s_device_mode;
}

void voice_set_mode(gap_mode_t mode)
{
    s_device_mode = mode;
}

gap_mode_t voice_toggle_mode(void)
{
    s_device_mode = (s_device_mode == GAP_MODE_PLAN) ? GAP_MODE_COACH : GAP_MODE_PLAN;
    ESP_LOGI(TAG, "Mode toggled to: %s", s_device_mode == GAP_MODE_COACH ? "COACH" : "PLAN");
    return s_device_mode;
}

const char *voice_get_mode_str(void)
{
    return (s_device_mode == GAP_MODE_COACH) ? "coach" : "plan";
}

esp_err_t voice_init(void)
{
    // Configure Push-to-Talk (GPIO 38), Accept (GPIO 1), and Cancel (GPIO 2) buttons
    gpio_config_t btn = {
        .pin_bit_mask = (1ULL << PIN_BTN_RECORD) | (1ULL << PIN_BTN_ACCEPT) | (1ULL << PIN_BTN_CANCEL),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    esp_err_t err = gpio_config(&btn);
    if (err == ESP_OK) {
        err = audio_play_init();
    }
    // The mic channel is created once and kept, so the speaker always gets the other I2S port.
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
    // RX buffer for the console UART so keystrokes from idf.py monitor can be read.
    if (err == ESP_OK && !uart_is_driver_installed(CONFIG_ESP_CONSOLE_UART_NUM)) {
        err = uart_driver_install(CONFIG_ESP_CONSOLE_UART_NUM, 256, 0, 0, NULL, 0);
    }
#endif
    ESP_LOGI(TAG, "Ready: hold talk button (GPIO 38/Enter) to talk; press Btn 1 (or 'c') to confirm; press Btn 2 (or 'x') to cancel");
    return err;
}

bool voice_button_pressed(void)
{
    return gpio_get_level(PIN_BTN_RECORD) == 0;
}

bool voice_accept_button_pressed(void)
{
    return gpio_get_level(PIN_BTN_ACCEPT) == 0;
}

bool voice_cancel_button_pressed(void)
{
    return gpio_get_level(PIN_BTN_CANCEL) == 0;
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
        vTaskDelay(pdMS_TO_TICKS(50));
        uart_flush_input(CONFIG_ESP_CONSOLE_UART_NUM);
    }
    return hit;
#else
    return false;
#endif
}

bool voice_serial_confirm_key(void)
{
#if CONFIG_ESP_CONSOLE_UART
    bool hit = false;
    uint8_t c;
    while (uart_read_bytes(CONFIG_ESP_CONSOLE_UART_NUM, &c, 1, 0) == 1) {
        hit |= (c == 'c' || c == 'C');
    }
    if (hit) {
        vTaskDelay(pdMS_TO_TICKS(50));
        uart_flush_input(CONFIG_ESP_CONSOLE_UART_NUM);
    }
    return hit;
#else
    return false;
#endif
}

bool voice_serial_cancel_key(void)
{
#if CONFIG_ESP_CONSOLE_UART
    bool hit = false;
    uint8_t c;
    while (uart_read_bytes(CONFIG_ESP_CONSOLE_UART_NUM, &c, 1, 0) == 1) {
        hit |= (c == 'x' || c == 'X');
    }
    if (hit) {
        vTaskDelay(pdMS_TO_TICKS(50));
        uart_flush_input(CONFIG_ESP_CONSOLE_UART_NUM);
    }
    return hit;
#else
    return false;
#endif
}

void voice_speaker_test(void);

static void beep(float hz, int ms)
{
    if (audio_play_begin(16000) != ESP_OK) {
        return;
    }
    int16_t buf[160];
    int total = 16 * ms;
    for (int done = 0; done < total; done += 160) {
        for (int i = 0; i < 160; i++) {
            buf[i] = (int16_t)(sinf(2.0f * (float)M_PI * hz * (done + i) / 16000.0f) * 10000.0f);
        }
        audio_play_write(buf, 160);
    }
    audio_play_end();
}

void voice_speaker_test(void)
{
    // Brief, gentle 70ms 440 Hz tone (A4) through the volume limiter instead of a sustained 1s blast
    beep(440.0f, 70);
}

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
    } else if (strcasecmp(evt->header_key, "X-Needs-Button") == 0) {
        h->needs_button = strcasecmp(evt->header_value, "true") == 0;
    } else if (strcasecmp(evt->header_key, "X-Proposal-Id") == 0) {
        strlcpy(h->proposal_id, evt->header_value, sizeof(h->proposal_id));
        strlcpy(s_active_proposal_id, evt->header_value, sizeof(s_active_proposal_id));
        ESP_LOGI(TAG, "Proposal ID registered: %s", s_active_proposal_id);
    } else if (strcasecmp(evt->header_key, "X-Conversation-Id") == 0) {
        strlcpy(h->conversation_id, evt->header_value, sizeof(h->conversation_id));
        strlcpy(s_active_conversation_id, evt->header_value, sizeof(s_active_conversation_id));
        ESP_LOGI(TAG, "Conversation ID registered: %s", s_active_conversation_id);
    } else if (strcasecmp(evt->header_key, "X-Device-Mode") == 0) {
        if (strcasecmp(evt->header_value, "coach") == 0) {
            s_device_mode = GAP_MODE_COACH;
        } else if (strcasecmp(evt->header_value, "plan") == 0) {
            s_device_mode = GAP_MODE_PLAN;
        }
    }
    return ESP_OK;
}

static bool write_all(esp_http_client_handle_t client, const uint8_t *data, size_t len)
{
    size_t sent = 0;
    while (sent < len) {
        int n = esp_http_client_write(client, (const char *)data + sent, len - sent);
        if (n <= 0) {
            return false;
        }
        sent += n;
    }
    return true;
}

static uint32_t le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint16_t le16(const uint8_t *p)
{
    return p[0] | (p[1] << 8);
}

static esp_err_t play_wav_stream(esp_http_client_handle_t client)
{
    // Read header into a small stack buffer (1024 bytes) without allocating large RAM
    uint8_t hdr[1024];
    int hdr_bytes = 0;
    while (hdr_bytes < (int)sizeof(hdr)) {
        int n = esp_http_client_read(client, (char *)hdr + hdr_bytes, sizeof(hdr) - hdr_bytes);
        if (n <= 0) break;
        hdr_bytes += n;
        if (hdr_bytes >= 44 && memcmp(hdr, "RIFF", 4) == 0) {
            for (int i = 12; i + 8 <= hdr_bytes; i++) {
                if (memcmp(hdr + i, "data", 4) == 0) {
                    goto header_ready;
                }
            }
        }
    }

header_ready:
    if (hdr_bytes < 44 || memcmp(hdr, "RIFF", 4) != 0 || memcmp(hdr + 8, "WAVE", 4) != 0) {
        ESP_LOGE(TAG, "Response is not valid RIFF/WAVE header (bytes=%d)", hdr_bytes);
        return ESP_FAIL;
    }

    uint16_t channels = 0, bits = 0;
    uint32_t rate = 0;
    int data_start = -1;
    uint32_t data_size = 0;

    int pos = 12;
    while (pos + 8 <= hdr_bytes) {
        uint32_t chunk_size = le32(hdr + pos + 4);
        if (memcmp(hdr + pos, "fmt ", 4) == 0 && pos + 8 + 16 <= hdr_bytes) {
            channels = le16(hdr + pos + 10);
            rate = le32(hdr + pos + 12);
            bits = le16(hdr + pos + 22);
        } else if (memcmp(hdr + pos, "data", 4) == 0) {
            data_start = pos + 8;
            data_size = chunk_size;
            break;
        }
        pos += 8 + (int)chunk_size + (int)(chunk_size & 1);
    }

    if (data_start < 0 || data_start >= hdr_bytes) {
        ESP_LOGE(TAG, "No data chunk found in WAV header buffer");
        return ESP_FAIL;
    }

    if (bits != 16 || channels < 1 || channels > 2 || rate < 8000 || rate > 48000) {
        ESP_LOGE(TAG, "Unsupported WAV format: %u ch, %u bit, %u Hz", channels, bits, (unsigned)rate);
        return ESP_ERR_NOT_SUPPORTED;
    }

    if (data_size == 0xFFFFFFFF) {
        ESP_LOGI(TAG, "Streaming audio playback: %u Hz, %u ch, declared data_size=0xFFFFFFFF (live stream)",
                 (unsigned)rate, channels);
    } else {
        ESP_LOGI(TAG, "Streaming audio playback: %u Hz, %u ch, declared data_size=%u bytes",
                 (unsigned)rate, channels, (unsigned)data_size);
    }

    const int frame_bytes = 2 * channels;
    #define STREAM_CHUNK_FRAMES 512
    #define STREAM_PREBUFFER_BYTES 12288
    static int16_t mono_buf[STREAM_CHUNK_FRAMES];
    static uint8_t s_prebuffer[STREAM_PREBUFFER_BYTES];
    static uint8_t raw_pcm[STREAM_CHUNK_FRAMES * 4];

    // Jitter pre-buffering: accumulate ~250ms of audio before starting I2S TX
    // to prevent DMA underruns caused by Wi-Fi packet latency / burst arrivals.
    int prebuf_len = 0;
    if (hdr_bytes > data_start) {
        int init_bytes = hdr_bytes - data_start;
        if (init_bytes > (int)sizeof(s_prebuffer)) {
            init_bytes = (int)sizeof(s_prebuffer);
        }
        memcpy(s_prebuffer, hdr + data_start, init_bytes);
        prebuf_len = init_bytes;
    }

    while (prebuf_len < (int)sizeof(s_prebuffer)) {
        int to_read = (int)sizeof(s_prebuffer) - prebuf_len;
        int n = esp_http_client_read(client, (char *)s_prebuffer + prebuf_len, to_read);
        if (n <= 0) {
            break; // Stream ended or EOF during prebuffering
        }
        prebuf_len += n;
    }

    if (prebuf_len == 0) {
        ESP_LOGW(TAG, "No audio payload received from stream");
        return ESP_FAIL;
    }

    esp_err_t err = audio_play_begin(rate);
    if (err != ESP_OK) {
        return err;
    }

    int total_frames_played = 0;
    int residual_bytes = 0;

    // Play all pre-buffered audio in safe batches of STREAM_CHUNK_FRAMES
    int prebuf_frames = prebuf_len / frame_bytes;
    for (int i = 0; i < prebuf_frames; i += STREAM_CHUNK_FRAMES) {
        int batch = prebuf_frames - i;
        if (batch > STREAM_CHUNK_FRAMES) batch = STREAM_CHUNK_FRAMES;
        for (int f = 0; f < batch; f++) {
            const uint8_t *sp = s_prebuffer + (i + f) * frame_bytes;
            int32_t s = (int16_t)le16(sp);
            if (channels == 2) {
                s = (s + (int16_t)le16(sp + 2)) / 2;
            }
            mono_buf[f] = (int16_t)s;
        }
        audio_play_write(mono_buf, batch);
        total_frames_played += batch;
    }
    residual_bytes = prebuf_len % frame_bytes;
    if (residual_bytes > 0) {
        memcpy(raw_pcm, s_prebuffer + prebuf_frames * frame_bytes, residual_bytes);
    }

    // Stream remaining audio chunks from HTTP client without buffer overflows
    while (true) {
        // Button responsiveness: if accept or cancel button is pressed during playback, stop early
        if (voice_accept_button_pressed() || voice_cancel_button_pressed()) {
            ESP_LOGI(TAG, "Playback interrupted by user button press");
            break;
        }

        int to_read = (int)sizeof(raw_pcm) - residual_bytes;
        int n = esp_http_client_read(client, (char *)raw_pcm + residual_bytes, to_read);
        if (n <= 0) {
            break;
        }
        int available = residual_bytes + n;
        int frames = available / frame_bytes;
        residual_bytes = available % frame_bytes;

        for (int i = 0; i < frames; i += STREAM_CHUNK_FRAMES) {
            int batch = frames - i;
            if (batch > STREAM_CHUNK_FRAMES) batch = STREAM_CHUNK_FRAMES;
            for (int f = 0; f < batch; f++) {
                const uint8_t *sp = raw_pcm + (i + f) * frame_bytes;
                int32_t s = (int16_t)le16(sp);
                if (channels == 2) {
                    s = (s + (int16_t)le16(sp + 2)) / 2;
                }
                mono_buf[f] = (int16_t)s;
            }
            audio_play_write(mono_buf, batch);
            total_frames_played += batch;
        }

        if (residual_bytes > 0) {
            memmove(raw_pcm, raw_pcm + frames * frame_bytes, residual_bytes);
        }
    }

    audio_play_stats_t stats = audio_play_get_stats();
    audio_play_end();
    ESP_LOGI(TAG, "Reply played: %.1f s (%d frames, %u bytes), underruns=%u, write_errors=%u",
             (double)total_frames_played / rate,
             total_frames_played,
             (unsigned)stats.total_bytes_sent,
             (unsigned)stats.underrun_count,
             (unsigned)stats.write_errors);
    return ESP_OK;
}

void voice_announce_mode(gap_mode_t mode)
{
    if (mode == GAP_MODE_COACH) {
        display_show("GAP-AI Coach", "Coach Mode Active", "Ask: Hey Coach...", "Hold 38: Talk");
    } else {
        display_show("GAP-AI Planner", "Plan Mode Active", "Schedule your plans", "Hold 38: Talk");
    }

    bool played = false;
    const char *base_url = settings_get_backend_url();
    if (base_url && strlen(base_url) > 0 && strcmp(base_url, "auto") != 0) {
        char url[256];
        snprintf(url, sizeof(url), "%s/voice/mode-announcement?mode=%s", base_url,
                 mode == GAP_MODE_COACH ? "coach" : "plan");
        esp_http_client_config_t cfg;
        api_client_config(&cfg, url);
        cfg.method = HTTP_METHOD_GET;
        cfg.timeout_ms = 5000;
        cfg.buffer_size = 4096;
        esp_http_client_handle_t client = esp_http_client_init(&cfg);
        if (client != NULL) {
            char auth_header[192];
            snprintf(auth_header, sizeof(auth_header), "Bearer %s", settings_get_device_token());
            esp_http_client_set_header(client, "Authorization", auth_header);
            esp_http_client_set_header(client, "Accept", "audio/wav");
            esp_err_t err = esp_http_client_open(client, 0);
            if (err == ESP_OK) {
                int64_t hdr_len = esp_http_client_fetch_headers(client);
                int st = esp_http_client_get_status_code(client);
                if (hdr_len >= 0 && st == 200) {
                    if (play_wav_stream(client) == ESP_OK) {
                        played = true;
                    }
                }
                esp_http_client_close(client);
            }
            esp_http_client_cleanup(client);
        }
    }

    if (!played) {
        if (mode == GAP_MODE_COACH) {
            beep(600, 70);
            vTaskDelay(pdMS_TO_TICKS(30));
            beep(900, 70);
            vTaskDelay(pdMS_TO_TICKS(30));
            beep(1200, 100);
        } else {
            beep(1000, 80);
            vTaskDelay(pdMS_TO_TICKS(30));
            beep(750, 100);
        }
    }
}

static void read_json_reply(esp_http_client_handle_t client, reply_headers_t *h)
{
    char *body = calloc(1, JSON_BODY_MAX + 1);
    if (body == NULL) {
        return;
    }
    int len = esp_http_client_read_response(client, body, JSON_BODY_MAX);
    if (len > 0) {
        ESP_LOGI(TAG, "Voice JSON body (%d bytes): %s", len, body);
    } else {
        ESP_LOGW(TAG, "Voice JSON body empty or unreadable: %d", len);
    }
    cJSON *root = len > 0 ? cJSON_Parse(body) : NULL;
    const cJSON *reply = cJSON_GetObjectItemCaseSensitive(root, "reply_text");
    const cJSON *transcript = cJSON_GetObjectItemCaseSensitive(root, "transcript");
    const cJSON *intent = cJSON_GetObjectItemCaseSensitive(root, "intent");
    const cJSON *proposal = cJSON_GetObjectItemCaseSensitive(root, "proposal");
    const cJSON *message = cJSON_GetObjectItemCaseSensitive(root, "message");
    const cJSON *spoken_recommendation =
        cJSON_GetObjectItemCaseSensitive(root, "spoken_recommendation");

    const cJSON *plan = cJSON_GetObjectItemCaseSensitive(root, "plan");
    const cJSON *parsed = cJSON_GetObjectItemCaseSensitive(root, "parsed_plan");
    const cJSON *parsed_intent = cJSON_IsObject(parsed) ? cJSON_GetObjectItemCaseSensitive(parsed, "intent") : NULL;
    const cJSON *clarify_q = cJSON_IsObject(parsed) ? cJSON_GetObjectItemCaseSensitive(parsed, "clarification_question") : NULL;

    if (cJSON_IsString(transcript)) {
        strlcpy(h->transcript, transcript->valuestring, sizeof(h->transcript));
    }
    if (cJSON_IsString(intent)) {
        strlcpy(h->intent, intent->valuestring, sizeof(h->intent));
    } else if (cJSON_IsString(parsed_intent)) {
        strlcpy(h->intent, parsed_intent->valuestring, sizeof(h->intent));
    }

    if (cJSON_IsString(reply)) {
        strlcpy(h->reply, reply->valuestring, sizeof(h->reply));
    } else if (cJSON_IsString(spoken_recommendation)) {
        strlcpy(h->reply, spoken_recommendation->valuestring, sizeof(h->reply));
    } else if (cJSON_IsString(message)) {
        strlcpy(h->reply, message->valuestring, sizeof(h->reply));
    } else if (strcmp(h->intent, "clarify") == 0) {
        if (cJSON_IsString(clarify_q) && clarify_q->valuestring[0] != '\0') {
            strlcpy(h->reply, clarify_q->valuestring, sizeof(h->reply));
        } else {
            strlcpy(h->reply, "Please specify date and time", sizeof(h->reply));
        }
    } else if (strcmp(h->intent, "unsupported") == 0) {
        strlcpy(h->reply, "Sorry, request could not be processed", sizeof(h->reply));
    } else if (cJSON_IsObject(plan)) {
        const cJSON *title = cJSON_GetObjectItemCaseSensitive(plan, "title");
        if (cJSON_IsString(title) && title->valuestring[0] != '\0') {
            snprintf(h->reply, sizeof(h->reply), "Plan added: %s", title->valuestring);
        } else {
            strlcpy(h->reply, "Plan successfully created", sizeof(h->reply));
        }
    } else if (strcmp(h->intent, "create_plan") == 0 && cJSON_IsObject(parsed)) {
        const cJSON *title = cJSON_GetObjectItemCaseSensitive(parsed, "title");
        if (cJSON_IsString(title) && title->valuestring[0] != '\0') {
            snprintf(h->reply, sizeof(h->reply), "Plan added: %s", title->valuestring);
        } else {
            strlcpy(h->reply, "Plan successfully created", sizeof(h->reply));
        }
    }

    if (cJSON_IsObject(proposal)) {
        h->needs_button = true;
        const cJSON *pid = cJSON_GetObjectItemCaseSensitive(proposal, "id");
        if (cJSON_IsString(pid) && pid->valuestring[0] != '\0') {
            strlcpy(h->proposal_id, pid->valuestring, sizeof(h->proposal_id));
            strlcpy(s_active_proposal_id, pid->valuestring, sizeof(s_active_proposal_id));
            ESP_LOGI(TAG, "Proposal ID registered from JSON: %s", s_active_proposal_id);
        }
    }
    const cJSON *cid = cJSON_GetObjectItemCaseSensitive(root, "conversation_id");
    if (cJSON_IsString(cid) && cid->valuestring[0] != '\0') {
        strlcpy(h->conversation_id, cid->valuestring, sizeof(h->conversation_id));
        strlcpy(s_active_conversation_id, cid->valuestring, sizeof(s_active_conversation_id));
        ESP_LOGI(TAG, "Conversation ID registered from JSON: %s", s_active_conversation_id);
    }
    cJSON_Delete(root);
    free(body);
}

// Sends recorded WAV to POST /voice and plays/displays English response.
static void send_and_reply(const uint8_t *wav, size_t wav_len)
{
    static const char head[] =
        "--" BOUNDARY "\r\n"
        "Content-Disposition: form-data; name=\"audio\"; filename=\"voice.wav\"\r\n"
        "Content-Type: audio/wav\r\n\r\n";
    static const char tail[] = "\r\n--" BOUNDARY "--\r\n";

    if (strcmp(settings_get_backend_url(), "auto") == 0 || strlen(settings_get_backend_url()) == 0) {
        display_show("Searching PC...", NULL, NULL, NULL);
        discover_backend(NULL, 0, 2000);
    }

    reply_headers_t h = {0};
    char url[256];
    snprintf(url, sizeof(url), "%s/voice", settings_get_backend_url());
    esp_http_client_config_t cfg;
    api_client_config(&cfg, url);
    cfg.method = HTTP_METHOD_POST;
    cfg.timeout_ms = VOICE_HTTP_TIMEOUT_MS;
    cfg.buffer_size = 8192;
    cfg.buffer_size_tx = 4096;
    cfg.event_handler = on_http_event;
    cfg.user_data = &h;

    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == NULL) {
        show_text("Error", "No HTTP client");
        return;
    }
    char auth_header[192];
    snprintf(auth_header, sizeof(auth_header), "Bearer %s", settings_get_device_token());
    esp_http_client_set_header(client, "Authorization", auth_header);
    esp_http_client_set_header(client, "Content-Type", "multipart/form-data; boundary=" BOUNDARY);
    esp_http_client_set_header(client, "Accept", "audio/wav, application/json");
    esp_http_client_set_header(client, "X-Device-Mode", voice_get_mode_str());
    if (s_active_conversation_id[0] != '\0') {
        esp_http_client_set_header(client, "X-Conversation-Id", s_active_conversation_id);
        ESP_LOGI(TAG, "Sending voice request (mode=%s) with active X-Conversation-Id: %s",
                 voice_get_mode_str(), s_active_conversation_id);
    } else {
        ESP_LOGI(TAG, "Sending voice request (mode=%s)", voice_get_mode_str());
    }

    display_show("Sending...", NULL, NULL, NULL);
    int64_t t0 = esp_timer_get_time();
    size_t total = strlen(head) + wav_len + strlen(tail);
    esp_err_t err = esp_http_client_open(client, total);
    if (err != ESP_OK && strncmp(settings_get_backend_url(), "http://", 7) == 0) {
        ESP_LOGW(TAG, "Connection to %s failed (%s), trying auto-discovery...", url, esp_err_to_name(err));
        esp_http_client_cleanup(client);
        display_show("Searching PC...", NULL, NULL, NULL);
        if (discover_backend(NULL, 0, 2000) == ESP_OK) {
            snprintf(url, sizeof(url), "%s/voice", settings_get_backend_url());
            api_client_config(&cfg, url);
            cfg.method = HTTP_METHOD_POST;
            cfg.timeout_ms = VOICE_HTTP_TIMEOUT_MS;
            cfg.buffer_size = 8192;
            cfg.buffer_size_tx = 4096;
            cfg.event_handler = on_http_event;
            cfg.user_data = &h;
            client = esp_http_client_init(&cfg);
            if (client != NULL) {
                esp_http_client_set_header(client, "Authorization", auth_header);
                esp_http_client_set_header(client, "Content-Type", "multipart/form-data; boundary=" BOUNDARY);
                esp_http_client_set_header(client, "Accept", "audio/wav, application/json");
                esp_http_client_set_header(client, "X-Device-Mode", voice_get_mode_str());
                if (s_active_conversation_id[0] != '\0') {
                    esp_http_client_set_header(client, "X-Conversation-Id", s_active_conversation_id);
                }
                display_show("Sending...", NULL, NULL, NULL);
                err = esp_http_client_open(client, total);
            }
        } else {
            show_text("Connection Error", "Cannot reach backend");
            return;
        }
    }
    bool sent = err == ESP_OK && write_all(client, (const uint8_t *)head, strlen(head)) &&
                write_all(client, wav, wav_len) && write_all(client, (const uint8_t *)tail, strlen(tail));
    if (!sent) {
        ESP_LOGE(TAG, "Upload to /voice failed: %s", esp_err_to_name(err));
        show_text("Connection Error", "Cannot reach backend");
        if (client) esp_http_client_cleanup(client);
        return;
    }

    display_show("Thinking...", NULL, NULL, NULL);
    int64_t hdr_len = esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);
    ESP_LOGI(TAG, "POST /voice -> HTTP %d (%s) in %lld ms", status, h.content_type,
             (esp_timer_get_time() - t0) / 1000);
    if (hdr_len < 0 || status <= 0) {
        // No HTTP response at all (socket timeout / connection dropped): there is no body to parse.
        ESP_LOGE(TAG, "No response from /voice (fetch_headers=%lld, status=%d)", (long long)hdr_len, status);
        show_text("No Response", "Server timed out. Try again.");
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return;
    }

    bool is_wav = strncmp(h.content_type, "audio/wav", 9) == 0;
    if ((status == 200 || status == 201) && is_wav) {
        ESP_LOGI(TAG, "Transcript: %s | Reply: %s | Intent: %s", h.transcript, h.reply, h.intent);
        if (h.needs_button) {
            display_show("Plan Drafted:", h.reply, NULL, "1: Accept  2: Cancel");
        } else if (strcmp(h.intent, "coach_recommendation") == 0) {
            display_show("Coach Idea:", h.reply, NULL, "1: Accept  2: Cancel");
        } else if (strcmp(h.intent, "clarify") == 0) {
            show_text("Clarification:", h.reply);
        } else {
            show_text(s_device_mode == GAP_MODE_COACH ? "GAP-AI Coach:" : "GAP-AI:", h.reply);
        }
        if (play_wav_stream(client) != ESP_OK) {
            show_text(s_device_mode == GAP_MODE_COACH ? "GAP-AI Coach:" : "GAP-AI:", h.reply);
        }
    } else {
        read_json_reply(client, &h);
        ESP_LOGI(TAG, "Transcript: %s | Reply: %s | Intent: %s", h.transcript, h.reply, h.intent);
        if (status == 200 || status == 201) {
            if (h.needs_button) {
                display_show("Plan Drafted:", h.reply, NULL, "1: Accept  2: Cancel");
                beep(880, 80);
            } else if (strcmp(h.intent, "clarify") == 0) {
                show_text("Clarification:", h.reply);
                beep(700, 100);
            } else if (strcmp(h.intent, "unsupported") == 0) {
                show_text("Not Understood", h.reply);
                beep(400, 150);
            } else {
                show_text("GAP-AI:", h.reply);
                // Audio confirmation tone: notifies user that plan was genuinely processed
                beep(1200, 120);
            }
        } else if (status == 401) {
            show_text("Auth Error", "Invalid DEVICE_TOKEN");
            beep(400, 200);
        } else {
            char title[24];
            snprintf(title, sizeof(title), "HTTP %d Error", status);
            show_text(title, h.reply[0] ? h.reply : "Server failed");
            beep(400, 200);
        }
    }

    if (strcmp(h.intent, "plan_confirmed") == 0 || strcmp(h.intent, "plan_cancelled") == 0) {
        s_active_conversation_id[0] = '\0';
        ESP_LOGI(TAG, "Voice conversation finished with intent '%s', cleared active conversation ID", h.intent);
    }

    esp_http_client_close(client);
    esp_http_client_cleanup(client);
}

void voice_accept_proposal(void)
{
    if (strlen(settings_get_device_token()) == 0) {
        show_text("Setup Missing", "Config: DEVICE_TOKEN");
        return;
    }

    beep(1200, 80);
    display_show("Confirming...", NULL, NULL, NULL);

    reply_headers_t h = {0};
    char url[256];
    if (s_active_proposal_id[0] != '\0') {
        snprintf(url, sizeof(url), "%s/plans/proposals/accept?proposal_id=%s", settings_get_backend_url(), s_active_proposal_id);
    } else {
        snprintf(url, sizeof(url), "%s/plans/proposals/accept", settings_get_backend_url());
    }
    esp_http_client_config_t cfg;
    api_client_config(&cfg, url);
    cfg.method = HTTP_METHOD_POST;
    cfg.timeout_ms = VOICE_HTTP_TIMEOUT_MS;
    cfg.buffer_size = 8192;
    cfg.event_handler = on_http_event;
    cfg.user_data = &h;

    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == NULL) {
        show_text("Error", "No HTTP client");
        return;
    }

    char auth_header[192];
    snprintf(auth_header, sizeof(auth_header), "Bearer %s", settings_get_device_token());
    esp_http_client_set_header(client, "Authorization", auth_header);
    esp_http_client_set_header(client, "Accept", "audio/wav, application/json");
    esp_http_client_set_header(client, "Content-Length", "0");

    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "POST %s failed to open: %s", url, esp_err_to_name(err));
        show_text("Network Error", "Connection failed");
        esp_http_client_cleanup(client);
        return;
    }

    int64_t hdr_len = esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);
    ESP_LOGI(TAG, "POST /plans/proposals/accept -> HTTP %d (content_type=%s, hdr_len=%lld)",
             status, h.content_type, (long long)hdr_len);

    if (hdr_len < 0 || status <= 0) {
        ESP_LOGE(TAG, "No response from /plans/proposals/accept (hdr_len=%lld, status=%d)",
                 (long long)hdr_len, status);
        show_text("No Response", "Server timed out");
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return;
    }

    bool is_wav = strncmp(h.content_type, "audio/wav", 9) == 0;
    if (status == 200) {
        s_active_proposal_id[0] = '\0';
        s_active_conversation_id[0] = '\0';
        show_text("Plan Confirmed!", h.reply[0] ? h.reply : "Saved to schedule");
        if (is_wav) {
            play_wav_stream(client);
        } else {
            read_json_reply(client, &h);
            beep(1200, 120);
        }
    } else {
        read_json_reply(client, &h);
        if (status == 404) {
            s_active_proposal_id[0] = '\0';
            s_active_conversation_id[0] = '\0';
            show_text("No Proposal", "No plan waiting for acceptance");
            beep(400, 150);
        } else if (status == 401) {
            show_text("Auth Error", "Invalid DEVICE_TOKEN");
            beep(400, 200);
        } else {
            show_text("Accept Failed", "Could not confirm plan");
            beep(400, 200);
        }
    }

    esp_http_client_close(client);
    esp_http_client_cleanup(client);
}

void voice_reject_proposal(void)
{
    if (strlen(settings_get_device_token()) == 0) {
        show_text("Setup Missing", "Config: DEVICE_TOKEN");
        return;
    }

    beep(600, 80);
    display_show("Cancelling...", NULL, NULL, NULL);

    reply_headers_t h = {0};
    char url[256];
    if (s_active_proposal_id[0] != '\0') {
        snprintf(url, sizeof(url), "%s/plans/proposals/reject?proposal_id=%s", settings_get_backend_url(), s_active_proposal_id);
    } else {
        snprintf(url, sizeof(url), "%s/plans/proposals/reject", settings_get_backend_url());
    }
    esp_http_client_config_t cfg;
    api_client_config(&cfg, url);
    cfg.method = HTTP_METHOD_POST;
    cfg.timeout_ms = VOICE_HTTP_TIMEOUT_MS;
    cfg.buffer_size = 8192;
    cfg.event_handler = on_http_event;
    cfg.user_data = &h;

    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == NULL) {
        show_text("Error", "No HTTP client");
        return;
    }

    char auth_header[192];
    snprintf(auth_header, sizeof(auth_header), "Bearer %s", settings_get_device_token());
    esp_http_client_set_header(client, "Authorization", auth_header);
    esp_http_client_set_header(client, "Accept", "audio/wav, application/json");
    esp_http_client_set_header(client, "Content-Length", "0");

    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "POST %s failed to open: %s", url, esp_err_to_name(err));
        show_text("Network Error", "Connection failed");
        esp_http_client_cleanup(client);
        return;
    }

    int64_t hdr_len = esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);
    ESP_LOGI(TAG, "POST /plans/proposals/reject -> HTTP %d (content_type=%s, hdr_len=%lld)",
             status, h.content_type, (long long)hdr_len);

    if (hdr_len < 0 || status <= 0) {
        ESP_LOGE(TAG, "No response from /plans/proposals/reject (hdr_len=%lld, status=%d)",
                 (long long)hdr_len, status);
        show_text("No Response", "Server timed out");
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return;
    }

    bool is_wav = strncmp(h.content_type, "audio/wav", 9) == 0;
    if (status == 200) {
        s_active_proposal_id[0] = '\0';
        s_active_conversation_id[0] = '\0';
        show_text("Plan Cancelled", h.reply[0] ? h.reply : "Draft discarded");
        if (is_wav) {
            play_wav_stream(client);
        } else {
            read_json_reply(client, &h);
            beep(600, 80);
        }
    } else {
        read_json_reply(client, &h);
        if (status == 404) {
            s_active_proposal_id[0] = '\0';
            s_active_conversation_id[0] = '\0';
            show_text("No Proposal", "No plan waiting to cancel");
            beep(400, 150);
        } else if (status == 401) {
            show_text("Auth Error", "Invalid DEVICE_TOKEN");
            beep(400, 200);
        } else {
            show_text("Cancel Failed", "Could not cancel plan");
            beep(400, 200);
        }
    }

    esp_http_client_close(client);
    esp_http_client_cleanup(client);
}

void voice_run_turn(voice_trigger_t trigger)
{
    if (strlen(settings_get_device_token()) == 0) {
        show_text("Setup Missing", "Config: DEVICE_TOKEN");
        return;
    }

    beep(880, 80); // listening cue

    if (audio_record_start(MAX_AUDIO_DURATION_SEC * 1000) != ESP_OK) {
        show_text("Error", "Mic initialization failed");
        return;
    }

    int64_t t0 = esp_timer_get_time();
    int shown = -1;
    const char *hint = trigger == VOICE_TRIGGER_SERIAL ? "Enter: send" : "Release to send";
    ESP_LOGI(TAG, "Recording... %s", trigger == VOICE_TRIGGER_SERIAL ? "press Enter to send" : "release to send");
    while (audio_record_is_recording()) {
        bool stop = trigger == VOICE_TRIGGER_SERIAL ? voice_serial_key() : !voice_button_pressed();
        if (stop) {
            break;
        }
        int left = MAX_AUDIO_DURATION_SEC - (int)((esp_timer_get_time() - t0) / 1000000);
        if (left != shown) {
            char line[24];
            snprintf(line, sizeof(line), "%d s remaining", left);
            display_show("Listening...", line, NULL, hint);
            shown = left;
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    int held_ms = (int)((esp_timer_get_time() - t0) / 1000);

    uint8_t *wav = NULL;
    size_t wav_len = 0;
    esp_err_t err = audio_record_stop(&wav, &wav_len);
    if (err != ESP_OK || wav == NULL) {
        show_text("Error", "No audio recorded");
        audio_record_free_buffer(wav);
        return;
    }
    if (trigger == VOICE_TRIGGER_BUTTON && held_ms < MIN_HOLD_MS) {
        audio_record_free_buffer(wav);
        show_text("To talk", "Hold the button");
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

bool voice_accept_button_pressed(void)
{
    return false;
}

bool voice_cancel_button_pressed(void)
{
    return false;
}

bool voice_serial_key(void)
{
    return false;
}

bool voice_serial_confirm_key(void)
{
    return false;
}

bool voice_serial_cancel_key(void)
{
    return false;
}

void voice_run_turn(voice_trigger_t trigger)
{
}

void voice_accept_proposal(void)
{
}

void voice_reject_proposal(void)
{
}

bool voice_has_pending_conversation(void)
{
    return false;
}

const char *voice_get_active_conversation_id(void)
{
    return "";
}

void voice_clear_active_conversation(void)
{
}

gap_mode_t voice_get_mode(void)
{
    return GAP_MODE_PLAN;
}

void voice_set_mode(gap_mode_t mode)
{
    (void)mode;
}

gap_mode_t voice_toggle_mode(void)
{
    return GAP_MODE_PLAN;
}

const char *voice_get_mode_str(void)
{
    return "plan";
}

void voice_announce_mode(gap_mode_t mode)
{
    (void)mode;
}

#endif
