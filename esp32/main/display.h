#pragma once

#include "esp_err.h"

// 128x32 OLED with a 6 px wide font: 4 rows of 21 characters.
#define DISPLAY_ROWS       4
#define DISPLAY_COLS       21
#define DISPLAY_LINE_BYTES (DISPLAY_COLS * 2 + 1) // Turkish letters are 2 bytes in UTF-8

// Starts the SSD1306 on the board's I2C pins. Fails (and every later call is a
// no-op) when no display answers, so the rest of the firmware keeps running.
esp_err_t display_init(void);

// Replaces the whole screen with up to four UTF-8 lines (NULL = empty row).
// Turkish letters are shown without accents (ş -> s) because the font is ASCII.
void display_show(const char *l0, const char *l1, const char *l2, const char *l3);

// Word-wraps text into lines of at most DISPLAY_COLS characters; returns the line count.
int display_wrap(const char *text, char lines[][DISPLAY_LINE_BYTES], int max_lines);
