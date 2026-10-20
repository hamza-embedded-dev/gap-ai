#include "api.h"
#include "display.h"
#include "esp_chip_info.h"
#include "esp_idf_version.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "wifi.h"

#if ESP_IDF_VERSION < ESP_IDF_VERSION_VAL(5, 1, 0)
#error "GAP-AI firmware needs ESP-IDF v5.1 or newer (v5.3 recommended)"
#endif

#define WIFI_CONNECT_TIMEOUT_MS 30000
#define HEALTH_INTERVAL_MS 30000

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

static void show_status(bool online, esp_err_t health)
{
    display_show("GAP-AI", online ? "Wi-Fi: bagli" : "Wi-Fi: baglaniyor...",
                 !online ? NULL : health == ESP_OK ? "Backend: OK" : "Backend: yanit yok", NULL);
}

void app_main(void)
{
    log_chip_info();
    init_nvs();
    display_init();
    show_status(false, ESP_FAIL);
    wifi_start();

    if (!wifi_wait_connected(WIFI_CONNECT_TIMEOUT_MS)) {
        ESP_LOGW(TAG, "No Wi-Fi after %d s, still retrying in the background", WIFI_CONNECT_TIMEOUT_MS / 1000);
    }

    while (true) {
        bool online = wifi_is_connected();
        show_status(online, online ? api_check_health() : ESP_FAIL);
        vTaskDelay(pdMS_TO_TICKS(HEALTH_INTERVAL_MS));
    }
}
