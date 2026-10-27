// settings.h - Persistent configuration storage in NVS for GAP-AI
#pragma once

#include <stdbool.h>
#include "esp_err.h"

#define SETTINGS_MAX_SSID_LEN     32
#define SETTINGS_MAX_PASS_LEN     64
#define SETTINGS_MAX_URL_LEN      128
#define SETTINGS_MAX_TOKEN_LEN    128

// Initialize settings system and load cached values from NVS.
// If NVS is unconfigured or empty, falls back to defaults in secrets.h.
esp_err_t settings_init(void);

// Getters for active configuration (thread-safe, always return non-NULL strings)
const char *settings_get_wifi_ssid(void);
const char *settings_get_wifi_password(void);
const char *settings_get_backend_url(void);
const char *settings_get_device_token(void);

// Saves new settings to NVS and updates the active cache.
// Pass NULL for any parameter to retain the current value.
esp_err_t settings_save(const char *ssid, const char *pass, const char *url, const char *token);

// Clears NVS stored configuration, reverting to secrets.h defaults on next boot.
esp_err_t settings_reset_defaults(void);
