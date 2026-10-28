#pragma once

#include <stdbool.h>
#include "esp_err.h"

// Configures the talk button (GPIO 38), accept button (GPIO 1), cancel button (GPIO 2), and initializes audio.
esp_err_t voice_init(void);

typedef enum {
    VOICE_TRIGGER_BUTTON, // record while talk button is held
    VOICE_TRIGGER_SERIAL, // record until the next Enter on the serial console
} voice_trigger_t;

// True while the talk button (PIN_BTN_RECORD / GPIO 38) is held down.
bool voice_button_pressed(void);

// True when the accept button (PIN_BTN_ACCEPT / GPIO 1) is pressed.
bool voice_accept_button_pressed(void);

// True when the cancel button (PIN_BTN_CANCEL / GPIO 2) is pressed.
bool voice_cancel_button_pressed(void);

// True when Enter or Space arrived on serial console.
bool voice_serial_key(void);

// True when 'c' or 'C' arrived on serial console (confirm shortcut).
bool voice_serial_confirm_key(void);

// True when 'x' or 'X' arrived on serial console (cancel shortcut).
bool voice_serial_cancel_key(void);

// One full voice turn: records (max 10s) until released or Enter, sends to POST /voice,
// plays spoken English reply on speaker, and displays response on OLED.
void voice_run_turn(voice_trigger_t trigger);

// Calls POST /plans/proposals/accept to confirm a pending plan proposal.
void voice_accept_proposal(void);

// Calls POST /plans/proposals/reject to cancel a pending plan proposal.
void voice_reject_proposal(void);

// True if a plan proposal is currently drafted and waiting for button 1/2 confirmation.
bool voice_has_pending_proposal(void);

// True if an interactive conversation is currently active across turns (e.g. clarification pending).
bool voice_has_pending_conversation(void);

// Returns active conversation ID or empty string if none.
const char *voice_get_active_conversation_id(void);

// Clears the active conversation ID.
void voice_clear_active_conversation(void);

// Temporary speaker hardware test.
void voice_speaker_test(void);
