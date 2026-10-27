#include "wifi.h"

#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/timers.h"
#include "secrets.h"
#include "settings.h"

#define WIFI_CONNECTED_BIT BIT0
#define RETRY_DELAY_MIN_MS 1000
#define RETRY_DELAY_MAX_MS 30000

static const char *TAG = "net";

static EventGroupHandle_t s_wifi_events;
static TimerHandle_t s_retry_timer;
static uint32_t s_retry_delay_ms = RETRY_DELAY_MIN_MS;

static void retry_timer_cb(TimerHandle_t timer)
{
    esp_wifi_connect();
}

static void schedule_retry(void)
{
    ESP_LOGW(TAG, "Retrying in %lu ms", (unsigned long)s_retry_delay_ms);
    xTimerChangePeriod(s_retry_timer, pdMS_TO_TICKS(s_retry_delay_ms), 0);
    xTimerStart(s_retry_timer, 0);

    s_retry_delay_ms *= 2;
    if (s_retry_delay_ms > RETRY_DELAY_MAX_MS) {
        s_retry_delay_ms = RETRY_DELAY_MAX_MS;
    }
}

static const char *disconnect_hint(uint8_t reason)
{
    switch (reason) {
    case WIFI_REASON_NO_AP_FOUND:
        return ": network not found, check WIFI_SSID and that it is 2.4 GHz";
    case WIFI_REASON_AUTH_FAIL:
    case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_HANDSHAKE_TIMEOUT:
        return ": authentication failed, check WIFI_PASSWORD";
    default:
        return "";
    }
}

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "Connecting to \"%s\"...", settings_get_wifi_ssid());
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *event = data;
        xEventGroupClearBits(s_wifi_events, WIFI_CONNECTED_BIT);
        ESP_LOGW(TAG, "Disconnected (reason %d)%s", event->reason, disconnect_hint(event->reason));
        schedule_retry();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = data;
        ESP_LOGI(TAG, "Connected, IP: " IPSTR, IP2STR(&event->ip_info.ip));
        s_retry_delay_ms = RETRY_DELAY_MIN_MS;
        xEventGroupSetBits(s_wifi_events, WIFI_CONNECTED_BIT);
    }
}

void wifi_start(void)
{
    s_wifi_events = xEventGroupCreate();
    s_retry_timer = xTimerCreate("wifi_retry", pdMS_TO_TICKS(RETRY_DELAY_MIN_MS), pdFALSE, NULL, retry_timer_cb);

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_cfg));

    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, NULL, NULL));

    const char *ssid = settings_get_wifi_ssid();
    const char *pass = settings_get_wifi_password();
    wifi_config_t wifi_cfg = {0};
    strlcpy((char *)wifi_cfg.sta.ssid, ssid, sizeof(wifi_cfg.sta.ssid));
    strlcpy((char *)wifi_cfg.sta.password, pass, sizeof(wifi_cfg.sta.password));
    // Accept open, WPA, WPA2, or WPA3 personal networks
    wifi_cfg.sta.threshold.authmode = WIFI_AUTH_OPEN;
    wifi_cfg.sta.pmf_cfg.capable = true;
    wifi_cfg.sta.pmf_cfg.required = false;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());
}

bool wifi_wait_connected(uint32_t timeout_ms)
{
    EventBits_t bits = xEventGroupWaitBits(s_wifi_events, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, pdMS_TO_TICKS(timeout_ms));
    return bits & WIFI_CONNECTED_BIT;
}

bool wifi_is_connected(void)
{
    return xEventGroupGetBits(s_wifi_events) & WIFI_CONNECTED_BIT;
}
