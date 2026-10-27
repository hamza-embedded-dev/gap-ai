// Board wiring: the single place for GPIO numbers (see esp32/README.md "Donanım bağlantısı").
#pragma once

#include "sdkconfig.h"

#if CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32
// ESP32-S3-DevKitC-1. Tested 2026-10-20: OLED, INMP441 and MAX98357A all verified on hardware.
#define BOARD_HAS_VOICE_HW 1

// SSD1306 128x32 OLED, I2C address 0x3C. VCC 3V3, GND top-right header.
#define PIN_OLED_SCL 7
#define PIN_OLED_SDA 15

// INMP441 I2S microphone. L/R tied to GND -> left slot. VDD 3V3.
#define PIN_MIC_SCK 4
#define PIN_MIC_WS  5
#define PIN_MIC_SD  6

// MAX98357A I2S amplifier. VIN 5V, GND bottom-left. GAIN unconnected (9 dB).
#define PIN_AMP_BCLK 11
#define PIN_AMP_LRC  12
#define PIN_AMP_DIN  13
#define PIN_AMP_SD   14 // HIGH = amp on, LOW = shutdown (mute)

// Push buttons to GND, internal pull-ups.
#define PIN_BTN_RECORD  38 // Talk button (hold to talk)
#define PIN_BTN_ACCEPT  1  // Button 1: Accept / confirm drafted plan
#define PIN_BTN_OUTCOME 1  // Alias
#define PIN_BTN_CANCEL  2  // Button 2: Reject / cancel drafted plan
#define PIN_BTN_REJECT  2  // Alias

#else
// No verified wiring for this chip yet: the firmware still builds and runs the
// Wi-Fi + /health loop, but the voice hardware stays disabled. Add a block above
// with your board's pins to enable it.
#define BOARD_HAS_VOICE_HW 0
#endif
