// Copy this file to `secrets.h` in the same folder and fill in your own values.
// `secrets.h` is gitignored. Never commit real Wi-Fi passwords or tokens.
#pragma once

// 2.4 GHz network only: ESP32 chips cannot join 5 GHz Wi-Fi.
#define WIFI_SSID "your-2.4ghz-ssid"
#define WIFI_PASSWORD "your-wifi-password"

// Backend base URL without a trailing slash.
//   Local backend on your computer: "http://192.168.1.50:8000"
//     (run uvicorn with --host 0.0.0.0 so the device can reach it)
//   Staging (HTTPS, verified with the built-in CA bundle): "https://<staging-host>"
#define BACKEND_BASE_URL "http://192.168.1.50:8000"

// Device Bearer token produced by backend/scripts/create_access_token.py (B3-3).
// Not needed for GET /health; used by later device endpoints.
#define DEVICE_TOKEN ""
