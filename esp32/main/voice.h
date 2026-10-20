#pragma once

#include <stdbool.h>

#include "esp_err.h"

// Configures the record button and puts the amplifier into shutdown.
esp_err_t voice_init(void);

typedef enum {
    VOICE_TRIGGER_BUTTON, // record while the button is held
    VOICE_TRIGGER_SERIAL, // record until the next Enter on the serial console
} voice_trigger_t;

// True while the record (push-to-talk) button is held down.
bool voice_button_pressed(void);

// True when Enter or Space arrived on the serial console since the last call.
// Lets you talk from `idf.py monitor` on a board without a button.
bool voice_serial_key(void);

// One full voice turn: records (max 10 s) until the button is released or Enter is
// pressed again, sends the WAV to POST /voice, then plays the spoken reply and shows
// the transcript and reply on the display. Blocks until done.
void voice_run_turn(voice_trigger_t trigger);
