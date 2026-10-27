// discover.h - UDP Auto-Discovery Client for GAP-AI Backend
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

#define DISCOVERY_DEFAULT_PORT 8001
#define DISCOVERY_DEFAULT_TIMEOUT_MS 2000

// Attempts to discover the GAP-AI backend server on the local network via UDP broadcast.
// If found, stores the URL (e.g. "http://192.168.89.212:8000") in out_url, saves it
// to persistent NVS settings, and returns ESP_OK.
// If not found or timed out, returns ESP_ERR_NOT_FOUND.
esp_err_t discover_backend(char *out_url, size_t max_len, uint32_t timeout_ms);
