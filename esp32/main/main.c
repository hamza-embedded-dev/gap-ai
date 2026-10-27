#include "api.h"
#include "board_pins.h"
#include "discover.h"
#include "display.h"
#include "esp_chip_info.h"
#include "esp_idf_version.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "portal.h"
#include "settings.h"
#include "voice.h"
#include "wifi.h"

#if ESP_IDF_VERSION < ESP_IDF_VERSION_VAL(5, 1, 0)
#error "GAP-AI firmware needs ESP-IDF v5.1 or newer (v5.3 recommended)"
#endif

#define WIFI_CONNECT_TIMEOUT_MS 30000
#define HEALTH_INTERVAL_MS 30000
#define POLL_MS 20
#define COMBO_HOLD_DURATION_MS 3000
#define BUTTON_DEBOUNCE_MS 60

static const char *TAG = "gap";

static void init_nvs(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
}

static void log_chip_info(void)
{
    esp_chip_info_t info;
    esp_chip_info(&info);
    ESP_LOGI(TAG, "GAP device starting on %s (rev %d.%d, %d core(s)), ESP-IDF v%d.%d.%d",
             CONFIG_IDF_TARGET, info.revision / 100, info.revision % 100, info.cores,
             ESP_IDF_VERSION_MAJOR, ESP_IDF_VERSION_MINOR, ESP_IDF_VERSION_PATCH);
}

static void show_idle(bool online)
{
    display_show("GAP-AI", online ? "Wi-Fi: Connected" : "Wi-Fi: Connecting...", NULL,
                 online ? "Hold 38:Talk 1:OK 2:X" : "Hold 1+2: Setup");
}

static void check_or_discover_backend(void)
{
    const char *url = settings_get_backend_url();
    bool is_local_or_auto = (strcmp(url, "auto") == 0 || strlen(url) == 0 || strncmp(url, "http://", 7) == 0);

    if (is_local_or_auto) {
        display_show("GAP-AI", "Wi-Fi: Connected", "Finding Server...", "Hold 1+2: Setup");
        char discovered[SETTINGS_MAX_URL_LEN + 1];
        if (discover_backend(discovered, sizeof(discovered), 2000) == ESP_OK) {
            const char *short_host = strncmp(discovered, "http://", 7) == 0 ? discovered + 7 : discovered;
            display_show("GAP-AI", "Server Found!", short_host, "Hold 38: Talk");
            vTaskDelay(pdMS_TO_TICKS(1200));
        }
    } else if (strncmp(url, "https://", 8) == 0) {
        const char *short_host = url + 8;
        display_show("GAP-AI Cloud", "Wi-Fi: Connected", short_host, "Verifying HTTPS...");
    }

    if (api_check_health() == ESP_OK) {
        display_show("GAP-AI Ready", "Backend: Online", NULL, "Hold 38:Talk 1:OK 2:X");
    } else {
        display_show("GAP-AI", "Backend Offline", "Check URL/Server", "Hold 1+2: Setup");
    }
}

void app_main(void)
{
    log_chip_info();
    init_nvs();
    settings_init();
    display_init();

    bool voice_ok = BOARD_HAS_VOICE_HW && voice_init() == ESP_OK;
    if (voice_ok) {
        ESP_LOGI(TAG, "Speaker test: 1 kHz tone for 1 second");
        voice_speaker_test();
    }
    if (!voice_ok) {
        ESP_LOGW(TAG, "Voice hardware disabled for this board (see board_pins.h)");
    }

    show_idle(false);
    wifi_start();

    bool online = false;
    int64_t next_health = 0;

    // Dual button hold state tracking
    int64_t both_held_start = 0;
    bool both_holding = false;
    bool suppress_single_clicks = false;
    int last_remaining_sec = -1;

    while (true) {
        int64_t now = esp_timer_get_time() / 1000;

        if (portal_is_active()) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        bool connected = wifi_is_connected();

        // 1. Dual-Button Combo Detection (Button 1: GPIO 1 & Button 2: GPIO 2)
        // Holding both buttons together for 3 seconds opens the Configuration Portal.
        bool b1 = voice_ok && voice_accept_button_pressed();
        bool b2 = voice_ok && voice_cancel_button_pressed();

        if (b1 && b2) {
            if (!both_holding) {
                both_holding = true;
                both_held_start = now;
                suppress_single_clicks = true;
                last_remaining_sec = -1;
                ESP_LOGI(TAG, "Buttons 1 & 2 held: hold for 3 seconds to enter setup mode...");
            }

            int64_t held_ms = now - both_held_start;
            int remaining_sec = (COMBO_HOLD_DURATION_MS - held_ms + 999) / 1000;
            if (remaining_sec < 0) remaining_sec = 0;

            if (remaining_sec != last_remaining_sec) {
                last_remaining_sec = remaining_sec;
                char line1[24];
                snprintf(line1, sizeof(line1), "Hold 1 & 2: %ds", remaining_sec);
                display_show("Setup Mode", line1, "Keep holding...", NULL);
            }

            if (held_ms >= COMBO_HOLD_DURATION_MS) {
                ESP_LOGI(TAG, "Both buttons held for 3 seconds: entering configuration portal!");
                portal_start();
                continue;
            }

            vTaskDelay(pdMS_TO_TICKS(POLL_MS));
            continue; // While both buttons are held, skip single button checks
        } else if (both_holding) {
            // User released buttons before 3 seconds
            ESP_LOGI(TAG, "Setup combo cancelled (released early)");
            both_holding = false;
            suppress_single_clicks = true; // Keep suppressed until all buttons are fully released
            both_held_start = 0;
            last_remaining_sec = -1;
            show_idle(wifi_is_connected());
        }

        // Reset single-click suppression once all buttons are fully released
        if (!b1 && !b2) {
            suppress_single_clicks = false;
        }

        // 2. Check Talk button (GPIO 38) or Enter on serial
        bool talk_btn = voice_ok && voice_button_pressed();
        bool talk_key = voice_ok && voice_serial_key();
        if (connected && (talk_btn || talk_key)) {
            voice_run_turn(talk_btn ? VOICE_TRIGGER_BUTTON : VOICE_TRIGGER_SERIAL);
            vTaskDelay(pdMS_TO_TICKS(3000)); // keep reply on OLED
            while (voice_button_pressed()) {
                vTaskDelay(pdMS_TO_TICKS(POLL_MS));
            }
            voice_serial_key(); // clear buffer
            if (!voice_has_pending_proposal()) {
                online = !connected;
            }
            ESP_LOGI(TAG, "Ready: hold talk button (GPIO 38) to talk; press 1 to accept, 2 to cancel");
        }

        // 3. Check Accept button (GPIO 1) or 'c' on serial
        bool accept_btn = voice_ok && b1 && !suppress_single_clicks;
        bool accept_key = voice_ok && voice_serial_confirm_key();
        if (connected && (accept_btn || accept_key)) {
            if (accept_btn) {
                // Anti-misclick debounce: ensure button 2 isn't being pressed slightly out of sync
                vTaskDelay(pdMS_TO_TICKS(BUTTON_DEBOUNCE_MS));
                if (voice_cancel_button_pressed()) {
                    continue; // Transition into dual-button hold
                }
            }
            voice_accept_proposal();
            vTaskDelay(pdMS_TO_TICKS(3000));
            while (voice_accept_button_pressed()) {
                vTaskDelay(pdMS_TO_TICKS(POLL_MS));
            }
            voice_serial_confirm_key();
            online = !connected;
        }

        // 4. Check Cancel button (GPIO 2) or 'x' on serial
        bool cancel_btn = voice_ok && b2 && !suppress_single_clicks;
        bool cancel_key = voice_ok && voice_serial_cancel_key();
        if (connected && (cancel_btn || cancel_key)) {
            if (cancel_btn) {
                // Anti-misclick debounce: ensure button 1 isn't being pressed slightly out of sync
                vTaskDelay(pdMS_TO_TICKS(BUTTON_DEBOUNCE_MS));
                if (voice_accept_button_pressed()) {
                    continue; // Transition into dual-button hold
                }
            }
            voice_reject_proposal();
            vTaskDelay(pdMS_TO_TICKS(3000));
            while (voice_cancel_button_pressed()) {
                vTaskDelay(pdMS_TO_TICKS(POLL_MS));
            }
            voice_serial_cancel_key();
            online = !connected;
        }

        if (connected != online) {
            online = connected;
            show_idle(online);
            if (online) {
                check_or_discover_backend();
                next_health = now + HEALTH_INTERVAL_MS;
            }
        }
        if (connected && now >= next_health) {
            esp_err_t err = api_check_health();
            if (err != ESP_OK) {
                const char *cur_url = settings_get_backend_url();
                if (strcmp(cur_url, "auto") == 0 || strncmp(cur_url, "http://", 7) == 0) {
                    ESP_LOGW(TAG, "Health check failed for %s, attempting auto-discovery...", cur_url);
                    char discovered[SETTINGS_MAX_URL_LEN + 1];
                    if (discover_backend(discovered, sizeof(discovered), 2000) == ESP_OK) {
                        api_check_health();
                    }
                }
            }
            next_health = now + HEALTH_INTERVAL_MS;
        }
        vTaskDelay(pdMS_TO_TICKS(POLL_MS));
    }
}
