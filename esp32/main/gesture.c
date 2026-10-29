#include "gesture.h"

void gesture_init(gesture_tracker_t *gt)
{
    if (!gt) return;
    gt->state = GESTURE_STATE_IDLE;
    gt->press_start_ms = 0;
    gt->dual_hold_start_ms = 0;
    gt->last_remaining_sec = -1;
    gt->remaining_sec = -1;
}

gesture_event_t gesture_update(gesture_tracker_t *gt, int64_t now_ms, bool b1_pressed, bool b2_pressed)
{
    if (!gt) return GESTURE_EVENT_NONE;

    switch (gt->state) {
    case GESTURE_STATE_IDLE:
        if (b1_pressed && b2_pressed) {
            gt->state = GESTURE_STATE_DUAL_HOLD;
            gt->dual_hold_start_ms = now_ms;
            gt->last_remaining_sec = -1;
            gt->remaining_sec = 3;
            return GESTURE_EVENT_HOLDING_SETUP;
        } else if (b1_pressed) {
            gt->state = GESTURE_STATE_B1_WAIT_SYNC;
            gt->press_start_ms = now_ms;
            return GESTURE_EVENT_NONE;
        } else if (b2_pressed) {
            gt->state = GESTURE_STATE_B2_WAIT_SYNC;
            gt->press_start_ms = now_ms;
            return GESTURE_EVENT_NONE;
        }
        return GESTURE_EVENT_NONE;

    case GESTURE_STATE_B1_WAIT_SYNC:
        if (b2_pressed) {
            // Button 2 pressed within sync window -> transition to dual hold
            gt->state = GESTURE_STATE_DUAL_HOLD;
            gt->dual_hold_start_ms = gt->press_start_ms; // start from initial press
            gt->last_remaining_sec = -1;
            gt->remaining_sec = 3;
            return GESTURE_EVENT_HOLDING_SETUP;
        }
        if (!b1_pressed) {
            // Button 1 released before Button 2 arrived
            int64_t held_ms = now_ms - gt->press_start_ms;
            gt->state = GESTURE_STATE_IDLE;
            if (held_ms >= GESTURE_DEBOUNCE_MS) {
                return GESTURE_EVENT_SINGLE_ACCEPT;
            }
            return GESTURE_EVENT_NONE;
        }
        if (now_ms - gt->press_start_ms > GESTURE_STAGGERED_THRESHOLD_MS) {
            // Staggered threshold exceeded, B2 was not pressed -> confirm single click
            gt->state = GESTURE_STATE_WAIT_RELEASE;
            return GESTURE_EVENT_SINGLE_ACCEPT;
        }
        return GESTURE_EVENT_NONE;

    case GESTURE_STATE_B2_WAIT_SYNC:
        if (b1_pressed) {
            // Button 1 pressed within sync window -> transition to dual hold
            gt->state = GESTURE_STATE_DUAL_HOLD;
            gt->dual_hold_start_ms = gt->press_start_ms;
            gt->last_remaining_sec = -1;
            gt->remaining_sec = 3;
            return GESTURE_EVENT_HOLDING_SETUP;
        }
        if (!b2_pressed) {
            // Button 2 released before Button 1 arrived
            int64_t held_ms = now_ms - gt->press_start_ms;
            gt->state = GESTURE_STATE_IDLE;
            if (held_ms >= GESTURE_DEBOUNCE_MS) {
                return GESTURE_EVENT_SINGLE_CANCEL;
            }
            return GESTURE_EVENT_NONE;
        }
        if (now_ms - gt->press_start_ms > GESTURE_STAGGERED_THRESHOLD_MS) {
            // Staggered threshold exceeded, B1 was not pressed -> confirm single click
            gt->state = GESTURE_STATE_WAIT_RELEASE;
            return GESTURE_EVENT_SINGLE_CANCEL;
        }
        return GESTURE_EVENT_NONE;

    case GESTURE_STATE_DUAL_HOLD:
        if (b1_pressed && b2_pressed) {
            int64_t held_ms = now_ms - gt->dual_hold_start_ms;
            int rem_sec = (GESTURE_COMBO_HOLD_DURATION_MS - (int)held_ms + 999) / 1000;
            if (rem_sec < 0) rem_sec = 0;
            gt->remaining_sec = rem_sec;

            if (held_ms >= GESTURE_COMBO_HOLD_DURATION_MS) {
                // Long 3-second hold reached -> Wi-Fi setup!
                gt->state = GESTURE_STATE_WAIT_RELEASE;
                return GESTURE_EVENT_COMBO_LONG_SETUP;
            }

            if (rem_sec != gt->last_remaining_sec) {
                gt->last_remaining_sec = rem_sec;
                return GESTURE_EVENT_HOLDING_SETUP;
            }
            return GESTURE_EVENT_NONE;
        } else {
            // Released before 3 seconds
            int64_t held_ms = now_ms - gt->dual_hold_start_ms;
            gt->state = GESTURE_STATE_WAIT_RELEASE;
            if (held_ms >= GESTURE_DEBOUNCE_MS) {
                // Valid short simultaneous combo -> Toggle Mode!
                return GESTURE_EVENT_COMBO_SHORT;
            }
            return GESTURE_EVENT_NONE;
        }

    case GESTURE_STATE_WAIT_RELEASE:
        if (!b1_pressed && !b2_pressed) {
            gt->state = GESTURE_STATE_IDLE;
        }
        return GESTURE_EVENT_NONE;
    }

    return GESTURE_EVENT_NONE;
}
