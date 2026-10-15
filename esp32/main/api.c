#include "api.h"

#include <string.h>

#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "secrets.h"

#define HTTP_TIMEOUT_MS 10000
#define HEALTH_BODY_MAX 256

static const char *TAG = "api";

static void init_client_config(esp_http_client_config_t *cfg, const char *url)
{
    memset(cfg, 0, sizeof(*cfg));
    cfg->url = url;
    cfg->timeout_ms = HTTP_TIMEOUT_MS;
    if (strncmp(url, "https://", 8) == 0) {
        // Verify the server certificate against the built-in root CA bundle.
        cfg->crt_bundle_attach = esp_crt_bundle_attach;
    }
}

esp_err_t api_check_health(void)
{
    const char *url = BACKEND_BASE_URL "/health";
    esp_http_client_config_t cfg;
    init_client_config(&cfg, url);

    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == NULL) {
        ESP_LOGE(TAG, "Could not create HTTP client");
        return ESP_FAIL;
    }

    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "GET %s failed: %s", url, esp_err_to_name(err));
        esp_http_client_cleanup(client);
        return err;
    }

    esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);

    char body[HEALTH_BODY_MAX + 1];
    int len = esp_http_client_read_response(client, body, HEALTH_BODY_MAX);
    body[len > 0 ? len : 0] = '\0';

    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    if (status == 200) {
        ESP_LOGI(TAG, "GET /health -> HTTP %d %s", status, body);
        return ESP_OK;
    }
    ESP_LOGE(TAG, "GET /health -> HTTP %d %s", status, body);
    return ESP_FAIL;
}
