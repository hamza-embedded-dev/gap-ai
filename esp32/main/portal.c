// portal.c - Captive portal and Web Configuration Server for GAP-AI
#include "portal.h"

#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "audio_feedback.h"
#include "display.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include "settings.h"

static const char *TAG = "portal";

static bool s_portal_active = false;
static httpd_handle_t s_http_server = NULL;
static esp_netif_t *s_ap_netif = NULL;
static int s_dns_socket = -1;

bool portal_is_active(void)
{
    return s_portal_active;
}

// URL decoding helper
static void url_decode(char *dst, const char *src, size_t max_len)
{
    size_t out = 0;
    while (*src && out + 1 < max_len) {
        if (*src == '+') {
            dst[out++] = ' ';
            src++;
        } else if (*src == '%' && isxdigit((int)src[1]) && isxdigit((int)src[2])) {
            char hex[3] = {src[1], src[2], '\0'};
            dst[out++] = (char)strtol(hex, NULL, 16);
            src += 3;
        } else {
            dst[out++] = *src++;
        }
    }
    dst[out] = '\0';
}

// Extracts a URL-encoded field from form body (e.g., "key=value&other=...")
static bool extract_form_value(const char *body, const char *key, char *out, size_t max_len)
{
    size_t key_len = strlen(key);
    const char *p = body;
    while (p && *p) {
        if (strncmp(p, key, key_len) == 0 && p[key_len] == '=') {
            const char *val_start = p + key_len + 1;
            const char *val_end = strchr(val_start, '&');
            size_t raw_len = val_end ? (size_t)(val_end - val_start) : strlen(val_start);

            char temp[256];
            size_t copy_len = raw_len < sizeof(temp) - 1 ? raw_len : sizeof(temp) - 1;
            memcpy(temp, val_start, copy_len);
            temp[copy_len] = '\0';

            url_decode(out, temp, max_len);
            return true;
        }
        p = strchr(p, '&');
        if (p) p++;
    }
    out[0] = '\0';
    return false;
}

// Deferred reboot task so HTTP response can finish transmitting
static void reboot_task(void *param)
{
    vTaskDelay(pdMS_TO_TICKS(1500));
    ESP_LOGI(TAG, "Rebooting device now with new configuration...");
    esp_restart();
}

// Lightweight DNS Responder on UDP Port 53
// Resolves every domain query to 192.168.4.1 for instant Captive Portal pop-ups
static void dns_server_task(void *pvParameters)
{
    uint8_t rx_buffer[128];
    uint8_t tx_buffer[128];
    struct sockaddr_in server_addr = {
        .sin_family = AF_INET,
        .sin_port = htons(53),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };

    s_dns_socket = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (s_dns_socket < 0) {
        ESP_LOGE(TAG, "Failed to create DNS socket: errno %d", errno);
        vTaskDelete(NULL);
        return;
    }

    if (bind(s_dns_socket, (struct sockaddr *)&server_addr, sizeof(server_addr)) < 0) {
        ESP_LOGE(TAG, "Failed to bind DNS socket: errno %d", errno);
        close(s_dns_socket);
        s_dns_socket = -1;
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "Captive DNS server running on port 53");

    while (1) {
        struct sockaddr_in client_addr;
        socklen_t client_addr_len = sizeof(client_addr);
        int len = recvfrom(s_dns_socket, rx_buffer, sizeof(rx_buffer), 0,
                           (struct sockaddr *)&client_addr, &client_addr_len);
        if (len < 12) continue; // Minimum valid DNS header size

        // Prepare response packet
        memcpy(tx_buffer, rx_buffer, len);
        // Flags: QR=1 (response), AA=1, RA=1, RCODE=0 (no error)
        tx_buffer[2] = 0x81;
        tx_buffer[3] = 0x80;
        // Answer count = 1
        tx_buffer[6] = 0x00;
        tx_buffer[7] = 0x01;

        // Append answer section: Pointer (0xc00c), Type A (0x0001), Class IN (0x0001), TTL 60s, Len 4, IP 192.168.4.1
        int tx_len = len;
        if (tx_len + 16 < (int)sizeof(tx_buffer)) {
            tx_buffer[tx_len++] = 0xc0;
            tx_buffer[tx_len++] = 0x0c; // Pointer to query name at offset 12
            tx_buffer[tx_len++] = 0x00;
            tx_buffer[tx_len++] = 0x01; // Type A
            tx_buffer[tx_len++] = 0x00;
            tx_buffer[tx_len++] = 0x01; // Class IN
            tx_buffer[tx_len++] = 0x00;
            tx_buffer[tx_len++] = 0x00;
            tx_buffer[tx_len++] = 0x00;
            tx_buffer[tx_len++] = 0x3c; // TTL 60 seconds
            tx_buffer[tx_len++] = 0x00;
            tx_buffer[tx_len++] = 0x04; // IP length: 4 bytes
            tx_buffer[tx_len++] = 192;
            tx_buffer[tx_len++] = 168;
            tx_buffer[tx_len++] = 4;
            tx_buffer[tx_len++] = 1;

            sendto(s_dns_socket, tx_buffer, tx_len, 0, (struct sockaddr *)&client_addr, client_addr_len);
        }
    }
}

static esp_err_t setup_get_handler(httpd_req_t *req)
{
    const char *ssid = settings_get_wifi_ssid();
    const char *pass = settings_get_wifi_password();
    const char *url = settings_get_backend_url();
    const char *token = settings_get_device_token();

    httpd_resp_set_type(req, "text/html");

    // Chunk 1: Header and styles
    httpd_resp_sendstr_chunk(req,
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>GAP-AI Device Setup</title>"
        "<style>"
        "* { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }"
        "body { background: #0f172a; color: #f8fafc; padding: 20px; display: flex; justify-content: center; align-items: center; min-height: 100vh; }"
        ".card { background: #1e293b; border-radius: 16px; padding: 24px; max-width: 440px; width: 100%; box-shadow: 0 10px 25px rgba(0,0,0,0.4); border: 1px solid #334155; }"
        ".header { text-align: center; margin-bottom: 24px; }"
        ".badge { display: inline-block; background: #2563eb; color: #fff; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 999px; text-transform: uppercase; margin-bottom: 8px; }"
        "h1 { font-size: 22px; font-weight: 700; color: #fff; }"
        "p.desc { font-size: 13px; color: #94a3b8; margin-top: 4px; }"
        ".group { margin-bottom: 16px; }"
        "label { display: block; font-size: 13px; font-weight: 600; color: #cbd5e1; margin-bottom: 6px; }"
        "input[type=\"text\"], input[type=\"password\"] { width: 100%; padding: 10px 12px; background: #0f172a; border: 1px solid #475569; border-radius: 8px; color: #fff; font-size: 14px; outline: none; }"
        "input:focus { border-color: #3b82f6; }"
        ".presets { display: flex; gap: 8px; margin-top: 6px; }"
        ".preset-btn { background: #334155; color: #cbd5e1; border: none; padding: 4px 8px; border-radius: 6px; font-size: 11px; cursor: pointer; }"
        ".preset-btn:hover { background: #475569; color: #fff; }"
        ".btn-submit { width: 100%; padding: 12px; background: #10b981; color: #fff; font-size: 15px; font-weight: 700; border: none; border-radius: 8px; cursor: pointer; margin-top: 8px; }"
        ".btn-submit:hover { background: #059669; }"
        ".footer { text-align: center; font-size: 12px; color: #64748b; margin-top: 16px; }"
        "</style></head><body><div class=\"card\">"
        "<div class=\"header\">"
        "<div class=\"badge\">GAP-AI Hardware</div>"
        "<h1>Device Configuration</h1>"
        "<p class=\"desc\">Configure Wi-Fi and backend connection</p>"
        "</div>"
        "<form method=\"POST\" action=\"/save\">"
    );

    // SSID field
    httpd_resp_sendstr_chunk(req,
        "<div class=\"group\">"
        "<label for=\"ssid\">Wi-Fi Network Name (2.4 GHz SSID)</label>"
        "<input type=\"text\" id=\"ssid\" name=\"ssid\" value=\""
    );
    httpd_resp_sendstr_chunk(req, ssid);
    httpd_resp_sendstr_chunk(req,
        "\" required placeholder=\"HomeNetwork_2.4GHz\"></div>"
    );

    // Password field with Show Password toggle
    httpd_resp_sendstr_chunk(req,
        "<div class=\"group\">"
        "<label for=\"password\">Wi-Fi Password</label>"
        "<input type=\"password\" id=\"password\" name=\"password\" value=\""
    );
    httpd_resp_sendstr_chunk(req, pass);
    httpd_resp_sendstr_chunk(req,
        "\" placeholder=\"Leave unchanged to keep saved password\">"
        "<div class=\"presets\">"
        "<button type=\"button\" class=\"preset-btn\" onclick=\"var p=document.getElementById('password');p.type=(p.type==='password'?'text':'password');\">Show / Hide Password</button>"
        "</div></div>"
    );

    // Backend URL field & presets
    httpd_resp_sendstr_chunk(req,
        "<div class=\"group\">"
        "<label for=\"backend_url\">Backend Base URL (Nebius HTTPS or Auto)</label>"
        "<input type=\"text\" id=\"backend_url\" name=\"backend_url\" value=\""
    );
    httpd_resp_sendstr_chunk(req, url);
    httpd_resp_sendstr_chunk(req,
        "\" placeholder=\"https://<your-nebius-endpoint> or auto\">"
        "<div class=\"presets\">"
        "<button type=\"button\" class=\"preset-btn\" onclick=\"var u=document.getElementById('backend_url');if(u.value.indexOf('https://')!==0)u.value='https://';u.focus();\">&#x2601; Nebius Serverless</button>"
        "<button type=\"button\" class=\"preset-btn\" onclick=\"document.getElementById('backend_url').value='auto'\">&#x2728; Auto Detect (Local PC)</button>"
        "<button type=\"button\" class=\"preset-btn\" onclick=\"document.getElementById('backend_url').value='https://gap-ai-backend.onrender.com'\">Render Cloud</button>"
        "</div></div>"
    );

    // Device token field & submit button
    httpd_resp_sendstr_chunk(req,
        "<div class=\"group\">"
        "<label for=\"device_token\">Device Bearer Token</label>"
        "<input type=\"text\" id=\"device_token\" name=\"device_token\" value=\""
    );
    httpd_resp_sendstr_chunk(req, token);
    httpd_resp_sendstr_chunk(req,
        "\" placeholder=\"Bearer Token\"></div>"
        "<button type=\"submit\" class=\"btn-submit\">Save to NVS Flash &amp; Restart</button>"
        "</form>"
        "<div class=\"footer\">Saved permanently in NVS Flash (survives resets &amp; power-offs) • Hold Buttons 1+2 for 3s anytime to reconfigure</div>"
        "</div></body></html>"
    );

    // Terminate response chunk stream
    httpd_resp_sendstr_chunk(req, NULL);
    return ESP_OK;
}

static esp_err_t save_post_handler(httpd_req_t *req)
{
    char buf[1024];
    int total_len = req->content_len;
    if (total_len >= (int)sizeof(buf)) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Payload too large");
        return ESP_FAIL;
    }

    int received = httpd_req_recv(req, buf, total_len);
    if (received <= 0) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Failed to read body");
        return ESP_FAIL;
    }
    buf[received] = '\0';

    char new_ssid[SETTINGS_MAX_SSID_LEN + 1] = {0};
    char new_pass[SETTINGS_MAX_PASS_LEN + 1] = {0};
    char new_url[SETTINGS_MAX_URL_LEN + 1] = {0};
    char new_token[SETTINGS_MAX_TOKEN_LEN + 1] = {0};

    extract_form_value(buf, "ssid", new_ssid, sizeof(new_ssid));
    extract_form_value(buf, "password", new_pass, sizeof(new_pass));
    extract_form_value(buf, "backend_url", new_url, sizeof(new_url));
    extract_form_value(buf, "device_token", new_token, sizeof(new_token));

    if (strlen(new_url) == 0) {
        strlcpy(new_url, "auto", sizeof(new_url));
    }

    ESP_LOGI(TAG, "Received new config: SSID=\"%s\", Backend=\"%s\", Token=%s",
             new_ssid, new_url, strlen(new_token) > 0 ? "[configured]" : "[empty]");

    // Pass NULL for any empty field so existing NVS values (e.g. password/token) are never accidentally wiped
    settings_save(
        new_ssid[0] ? new_ssid : NULL,
        new_pass[0] ? new_pass : NULL,
        new_url[0] ? new_url : NULL,
        new_token[0] ? new_token : NULL
    );

    display_show("GAP-AI Setup", "Settings Saved!", "Connecting Wi-Fi", "Restarting...");
    audio_feedback_play(AUDIO_FEEDBACK_WIFI_SETUP_SUCCESS);

    const char *resp_html =
        "<!DOCTYPE html><html><head><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>GAP-AI Saved</title>"
        "<style>body{background:#0f172a;color:#f8fafc;font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;padding:20px;text-align:center}"
        ".card{background:#1e293b;padding:32px;border-radius:16px;max-width:380px;box-shadow:0 10px 25px rgba(0,0,0,0.5);border:1px solid #334155}"
        "h2{color:#10b981;margin-top:0}p{color:#94a3b8;line-height:1.5}</style></head>"
        "<body><div class=\"card\"><h2>&#10004; Settings Saved!</h2>"
        "<p>The device is restarting and connecting to your Wi-Fi network.</p>"
        "<p>You can now reconnect to your normal Wi-Fi.</p>"
        "</div></body></html>";

    httpd_resp_set_type(req, "text/html");
    httpd_resp_send(req, resp_html, HTTPD_RESP_USE_STRLEN);

    // Launch deferred reboot
    xTaskCreate(reboot_task, "reboot_task", 2048, NULL, 5, NULL);
    return ESP_OK;
}

void portal_start(void)
{
    if (s_portal_active) {
        return;
    }
    s_portal_active = true;

    ESP_LOGI(TAG, "Entering Configuration Portal mode (SoftAP: GAP-AI-Setup)...");

    display_show("GAP-AI Config", "AP: GAP-AI-Setup", "Open Browser:", "http://192.168.4.1");
    audio_feedback_play(AUDIO_FEEDBACK_WIFI_SETUP_OPENED);

    // Stop station Wi-Fi if running
    esp_wifi_stop();

    // Create AP netif if not already created
    if (!s_ap_netif) {
        s_ap_netif = esp_netif_create_default_wifi_ap();
    }

    wifi_config_t ap_config = {
        .ap = {
            .ssid = "GAP-AI-Setup",
            .ssid_len = strlen("GAP-AI-Setup"),
            .channel = 1,
            .password = "",
            .max_connection = 4,
            .authmode = WIFI_AUTH_OPEN,
        },
    };

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    // Start Captive DNS server task
    xTaskCreate(dns_server_task, "dns_task", 2560, NULL, 5, NULL);

    // Start HTTP server on port 80 with wildcard matching
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.stack_size = 8192;
    config.max_uri_handlers = 8;
    config.lru_purge_enable = true;
    config.uri_match_fn = httpd_uri_match_wildcard;

    if (httpd_start(&s_http_server, &config) == ESP_OK) {
        // Register POST handler for form saving
        httpd_uri_t uri_save = {
            .uri = "/save",
            .method = HTTP_POST,
            .handler = save_post_handler,
            .user_ctx = NULL,
        };
        httpd_register_uri_handler(s_http_server, &uri_save);

        // Wildcard GET handler: serves setup HTML for all queries (/, /generate_204, /hotspot-detect.html, etc.)
        httpd_uri_t uri_get_all = {
            .uri = "/*",
            .method = HTTP_GET,
            .handler = setup_get_handler,
            .user_ctx = NULL,
        };
        httpd_register_uri_handler(s_http_server, &uri_get_all);

        ESP_LOGI(TAG, "Config Web Server started on http://192.168.4.1 (with wildcard matching)");
    } else {
        ESP_LOGE(TAG, "Failed to start HTTP server!");
        display_show("Setup Error", "Failed to start AP", NULL, NULL);
    }
}
