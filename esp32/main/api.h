#pragma once

#include "esp_err.h"
#include "esp_http_client.h"

// Calls GET {BACKEND_BASE_URL}/health and logs the status code and body.
// Returns ESP_OK only for an HTTP 200 response.
esp_err_t api_check_health(void);

// Fills an HTTP client config for url with the shared timeout, and the built-in CA
// bundle for https:// URLs. Callers may override fields (method, timeout, handlers).
void api_client_config(esp_http_client_config_t *cfg, const char *url);
