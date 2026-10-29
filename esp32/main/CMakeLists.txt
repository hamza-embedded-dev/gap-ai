if(NOT EXISTS "${CMAKE_CURRENT_LIST_DIR}/secrets.h")
    message(FATAL_ERROR
        "esp32/main/secrets.h not found.\n"
        "Copy esp32/main/secrets.example.h to esp32/main/secrets.h and fill in your Wi-Fi and backend settings.\n"
        "secrets.h is gitignored; never commit it.")
endif()

idf_component_register(
    SRCS "main.c" "wifi.c" "api.c" "audio_record.c" "audio_play.c" "audio_limiter.c" "display.c" "voice.c" "settings.c" "portal.c" "discover.c" "gesture.c"
    INCLUDE_DIRS "."
    REQUIRES esp_wifi esp_netif esp_event nvs_flash esp_http_client esp_http_server esp-tls mbedtls esp_driver_i2s esp_driver_i2c esp_driver_gpio esp_driver_uart esp_timer cjson
)
