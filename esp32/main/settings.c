// settings.c - Persistent configuration storage in NVS for GAP-AI
#include "settings.h"

#include <string.h>
#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "secrets.h"

static const char *TAG = "settings";
static const char *NVS_NAMESPACE = "gap_cfg";

static char s_wifi_ssid[SETTINGS_MAX_SSID_LEN + 1] = {0};
static char s_wifi_pass[SETTINGS_MAX_PASS_LEN + 1] = {0};
static char s_backend_url[SETTINGS_MAX_URL_LEN + 1] = {0};
static char s_device_token[SETTINGS_MAX_TOKEN_LEN + 1] = {0};

static void load_or_default(nvs_handle_t handle, const char *key, char *buf, size_t buf_size, const char *default_val)
{
    size_t required_len = 0;
    esp_err_t err = nvs_get_str(handle, key, NULL, &required_len);
    if (err == ESP_OK && required_len > 1 && required_len <= buf_size) {
        err = nvs_get_str(handle, key, buf, &required_len);
        if (err == ESP_OK && buf[0] != '\0') {
            return;
        }
    }
    // Only if NVS has no value yet, initialize from secrets.h and commit to NVS
    strlcpy(buf, default_val ? default_val : "", buf_size);
    if (buf[0] != '\0') {
        nvs_set_str(handle, key, buf);
    }
}

esp_err_t settings_init(void)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "Could not open NVS namespace \"%s\" (%s), using secrets.h defaults",
                 NVS_NAMESPACE, esp_err_to_name(err));
        strlcpy(s_wifi_ssid, WIFI_SSID, sizeof(s_wifi_ssid));
        strlcpy(s_wifi_pass, WIFI_PASSWORD, sizeof(s_wifi_pass));
        strlcpy(s_backend_url, BACKEND_BASE_URL, sizeof(s_backend_url));
        strlcpy(s_device_token, DEVICE_TOKEN, sizeof(s_device_token));
        return err;
    }

    load_or_default(handle, "wifi_ssid", s_wifi_ssid, sizeof(s_wifi_ssid), WIFI_SSID);
    load_or_default(handle, "wifi_pass", s_wifi_pass, sizeof(s_wifi_pass), WIFI_PASSWORD);
    load_or_default(handle, "backend_url", s_backend_url, sizeof(s_backend_url), BACKEND_BASE_URL);
    load_or_default(handle, "device_token", s_device_token, sizeof(s_device_token), DEVICE_TOKEN);

    nvs_commit(handle);
    nvs_close(handle);

    ESP_LOGI(TAG, "Loaded persistent NVS settings: SSID=\"%s\", Backend=\"%s\", Token=%s",
             s_wifi_ssid, s_backend_url, strlen(s_device_token) > 0 ? "[configured]" : "[empty]");
    return ESP_OK;
}

const char *settings_get_wifi_ssid(void)
{
    return s_wifi_ssid;
}

const char *settings_get_wifi_password(void)
{
    return s_wifi_pass;
}

const char *settings_get_backend_url(void)
{
    return s_backend_url;
}

const char *settings_get_device_token(void)
{
    return s_device_token;
}

esp_err_t settings_save(const char *ssid, const char *pass, const char *url, const char *token)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to open NVS for writing: %s", esp_err_to_name(err));
        return err;
    }

    if (ssid != NULL && strlen(ssid) > 0) {
        strlcpy(s_wifi_ssid, ssid, sizeof(s_wifi_ssid));
        nvs_set_str(handle, "wifi_ssid", s_wifi_ssid);
    }
    if (pass != NULL) {
        strlcpy(s_wifi_pass, pass, sizeof(s_wifi_pass));
        nvs_set_str(handle, "wifi_pass", s_wifi_pass);
    }
    if (url != NULL && strlen(url) > 0) {
        // Remove trailing slash if present
        char clean_url[SETTINGS_MAX_URL_LEN + 1];
        strlcpy(clean_url, url, sizeof(clean_url));
        size_t len = strlen(clean_url);
        while (len > 0 && clean_url[len - 1] == '/') {
            clean_url[len - 1] = '\0';
            len--;
        }
        strlcpy(s_backend_url, clean_url, sizeof(s_backend_url));
        nvs_set_str(handle, "backend_url", s_backend_url);
    }
    if (token != NULL) {
        strlcpy(s_device_token, token, sizeof(s_device_token));
        nvs_set_str(handle, "device_token", s_device_token);
    }

    err = nvs_commit(handle);
    nvs_close(handle);

    if (err == ESP_OK) {
        ESP_LOGI(TAG, "Settings successfully saved to NVS");
    } else {
        ESP_LOGE(TAG, "Failed to commit settings to NVS: %s", esp_err_to_name(err));
    }
    return err;
}

esp_err_t settings_reset_defaults(void)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        return err;
    }
    nvs_erase_all(handle);
    nvs_commit(handle);
    nvs_close(handle);
    return settings_init();
}
