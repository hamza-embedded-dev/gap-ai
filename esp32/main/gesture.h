#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define GESTURE_DEBOUNCE_MS           60
#define GESTURE_STAGGERED_THRESHOLD_MS 250
#define GESTURE_COMBO_HOLD_DURATION_MS 3000

typedef enum {
    GESTURE_EVENT_NONE = 0,
    GESTURE_EVENT_SINGLE_ACCEPT,      // Clean Button 1 click
    GESTURE_EVENT_SINGLE_CANCEL,      // Clean Button 2 click
    GESTURE_EVENT_COMBO_SHORT,        // Simultaneous Button 1 + 2 released before 3s (Toggle Mode)
    GESTURE_EVENT_COMBO_LONG_SETUP,   // Simultaneous Button 1 + 2 held for >= 3s (Wi-Fi Setup)
    GESTURE_EVENT_HOLDING_SETUP,      // Progress update while holding dual buttons
} gesture_event_t;

typedef enum {
    GESTURE_STATE_IDLE = 0,
    GESTURE_STATE_B1_WAIT_SYNC,
    GESTURE_STATE_B2_WAIT_SYNC,
    GESTURE_STATE_DUAL_HOLD,
    GESTURE_STATE_WAIT_RELEASE,
} gesture_state_t;

typedef struct {
    gesture_state_t state;
    int64_t press_start_ms;
    int64_t dual_hold_start_ms;
    int last_remaining_sec;
    int remaining_sec;
} gesture_tracker_t;

void gesture_init(gesture_tracker_t *gt);

gesture_event_t gesture_update(gesture_tracker_t *gt, int64_t now_ms, bool b1_pressed, bool b2_pressed);

#ifdef __cplusplus
}
#endif
