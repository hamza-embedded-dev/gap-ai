#pragma once

#include "esp_err.h"

// Calls GET {BACKEND_BASE_URL}/health and logs the status code and body.
// Returns ESP_OK only for an HTTP 200 response.
esp_err_t api_check_health(void);
