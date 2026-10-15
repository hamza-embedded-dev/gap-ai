#pragma once

#include <stdbool.h>
#include <stdint.h>

// Starts Wi-Fi in station mode with the credentials from secrets.h and keeps
// retrying in the background after a disconnect.
void wifi_start(void);

// Blocks until the device has an IP address or the timeout expires.
bool wifi_wait_connected(uint32_t timeout_ms);

bool wifi_is_connected(void);
