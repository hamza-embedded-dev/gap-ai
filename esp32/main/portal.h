// portal.h - Web Configuration Portal & SoftAP for GAP-AI
#pragma once

#include <stdbool.h>

// Enters SoftAP mode (SSID: "GAP-AI-Setup") and runs a web server at http://192.168.4.1.
// Displays setup instructions on OLED and waits for user configuration.
// Reboots automatically when settings are saved.
void portal_start(void);

// Returns true if configuration portal is currently running.
bool portal_is_active(void);
