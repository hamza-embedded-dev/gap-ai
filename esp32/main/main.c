#include "api.h"
#include "board_pins.h"
#include "display.h"
#include "esp_chip_info.h"
#include "esp_idf_version.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "voice.h"
#include "wifi.h"

#if ESP_IDF_VERSION < ESP_IDF_VERSION_VAL(5, 1, 0)
#error "GAP-AI firmware needs ESP-IDF v5.1 or newer (v5.3 recommended)"
#endif

#define WIFI_CONNECT_TIMEOUT_MS 30000
#define HEALTH_INTERVAL_MS 30000
#define POLL_MS 20

static const char *TAG = "gap";

static void init_nvs(void)
{
    // Wi-Fi stores calibration data in NVS.
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
    display_show("GAP-AI", online ? "Wi-Fi: bagli" : "Wi-Fi: baglaniyor...", NULL,
                  online ? "Konus: Enter / buton" : NULL);
}

void app_main(void)
{
    log_chip_info();
    init_nvs();
    display_init();
    bool voice_ok = BOARD_HAS_VOICE_HW && voice_init() == ESP_OK;
    if (!voice_ok) {
        ESP_LOGW(TAG, "Voice hardware disabled for this board (see board_pins.h)");
    }

    show_idle(false);
    wifi_start();
    if (!wifi_wait_connected(WIFI_CONNECT_TIMEOUT_MS)) {
        ESP_LOGW(TAG, "No Wi-Fi after %d s, still retrying in the background", WIFI_CONNECT_TIMEOUT_MS / 1000);
    }

    bool online = !wifi_is_connected(); // force the first idle screen refresh
    int64_t next_health = 0;
    while (true) {
        int64_t now = esp_timer_get_time() / 1000;
        bool connected = wifi_is_connected();

        bool button = voice_ok && voice_button_pressed();
        bool key = voice_ok && voice_serial_key();
        if (connected && (button || key)) {
            voice_run_turn(button ? VOICE_TRIGGER_BUTTON : VOICE_TRIGGER_SERIAL);
            vTaskDelay(pdMS_TO_TICKS(3000)); // keep the reply on screen
            while (voice_button_pressed()) {
                vTaskDelay(pdMS_TO_TICKS(POLL_MS)); // wait for release before re-arming
            }
            voice_serial_key(); // drop keys typed during the turn
            online = !connected;
            ESP_LOGI(TAG, "Ready: press Enter to talk again");
        }

        if (connected != online) {
            online = connected;
            show_idle(online);
        }
        if (connected && now >= next_health) {
            api_check_health();
            next_health = now + HEALTH_INTERVAL_MS;
        }
        vTaskDelay(pdMS_TO_TICKS(POLL_MS));
    }
}
