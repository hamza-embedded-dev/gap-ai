// discover.c - UDP Auto-Discovery Client for GAP-AI Backend
#include "discover.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "display.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"
#include "settings.h"

static const char *TAG = "discover";

esp_err_t discover_backend(char *out_url, size_t max_len, uint32_t timeout_ms)
{
    ESP_LOGI(TAG, "Starting auto-discovery broadcast for GAP-AI backend...");

    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) {
        ESP_LOGE(TAG, "Unable to create socket: errno %d", errno);
        return ESP_FAIL;
    }

    int broadcast_en = 1;
    if (setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &broadcast_en, sizeof(broadcast_en)) < 0) {
        ESP_LOGW(TAG, "Failed to set SO_BROADCAST: errno %d", errno);
    }

    struct timeval tv;
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    if (tv.tv_sec == 0 && tv.tv_usec == 0) {
        tv.tv_sec = 2;
    }
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    // Determine subnet broadcast address
    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    uint32_t subnet_bcast = INADDR_BROADCAST;
    if (netif) {
        esp_netif_ip_info_t ip_info;
        if (esp_netif_get_ip_info(netif, &ip_info) == ESP_OK && ip_info.ip.addr != 0) {
            subnet_bcast = ip_info.ip.addr | (~ip_info.netmask.addr);
        }
    }

    const char *payload = "GAP_DISCOVER\n";
    size_t payload_len = strlen(payload);

    // Destination 1: Global broadcast 255.255.255.255:8001
    struct sockaddr_in dest_addr1 = {
        .sin_family = AF_INET,
        .sin_port = htons(DISCOVERY_DEFAULT_PORT),
        .sin_addr.s_addr = htonl(INADDR_BROADCAST),
    };

    // Destination 2: Subnet broadcast (e.g. 192.168.89.255:8001)
    struct sockaddr_in dest_addr2 = {
        .sin_family = AF_INET,
        .sin_port = htons(DISCOVERY_DEFAULT_PORT),
        .sin_addr.s_addr = subnet_bcast,
    };

    // Send discovery packets
    sendto(sock, payload, payload_len, 0, (struct sockaddr *)&dest_addr1, sizeof(dest_addr1));
    sendto(sock, payload, payload_len, 0, (struct sockaddr *)&dest_addr2, sizeof(dest_addr2));

    char rx_buffer[128];
    struct sockaddr_in from_addr;
    socklen_t from_len = sizeof(from_addr);

    int len = recvfrom(sock, rx_buffer, sizeof(rx_buffer) - 1, 0, (struct sockaddr *)&from_addr, &from_len);
    close(sock);

    if (len <= 0) {
        ESP_LOGW(TAG, "Discovery timed out (no response on port %d)", DISCOVERY_DEFAULT_PORT);
        return ESP_ERR_NOT_FOUND;
    }

    rx_buffer[len] = '\0';
    ESP_LOGI(TAG, "Discovery response from %s:%d: \"%s\"",
             inet_ntoa(from_addr.sin_addr), ntohs(from_addr.sin_port), rx_buffer);

    // Parse response: "GAP_SERVER:<port>"
    int server_port = 8000;
    if (strncmp(rx_buffer, "GAP_SERVER:", 11) == 0) {
        server_port = atoi(rx_buffer + 11);
        if (server_port <= 0 || server_port > 65535) {
            server_port = 8000;
        }
    }

    char discovered_url[SETTINGS_MAX_URL_LEN + 1];
    snprintf(discovered_url, sizeof(discovered_url), "http://%s:%d",
             inet_ntoa(from_addr.sin_addr), server_port);

    ESP_LOGI(TAG, "Auto-discovered backend server URL: %s", discovered_url);

    if (out_url && max_len > 0) {
        strlcpy(out_url, discovered_url, max_len);
    }

    // Persist discovered URL into NVS so future calls use it
    settings_save(NULL, NULL, discovered_url, NULL);

    return ESP_OK;
}
