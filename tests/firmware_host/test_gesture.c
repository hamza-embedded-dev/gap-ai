#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
#include "../../esp32/main/gesture.h"

static void test_clean_short_combo(void)
{
    gesture_tracker_t gt;
    gesture_init(&gt);

    // Both pressed at t=100ms
    gesture_event_t ev = gesture_update(&gt, 100, true, true);
    assert(ev == GESTURE_EVENT_HOLDING_SETUP);

    // Still holding at t=500ms
    ev = gesture_update(&gt, 500, true, true);
    // Might be holding event or none, but NOT combo_short or long_setup
    assert(ev != GESTURE_EVENT_COMBO_SHORT);
    assert(ev != GESTURE_EVENT_COMBO_LONG_SETUP);

    // Released at t=700ms (held for 600ms < 3000ms)
    ev = gesture_update(&gt, 700, false, false);
    assert(ev == GESTURE_EVENT_COMBO_SHORT);

    // Still released at t=720ms: must return NONE (fires exactly once)
    ev = gesture_update(&gt, 720, false, false);
    assert(ev == GESTURE_EVENT_NONE);
    printf("PASS: test_clean_short_combo\n");
}

static void test_long_hold_wifi_setup(void)
{
    gesture_tracker_t gt;
    gesture_init(&gt);

    // Both pressed at t=100ms
    gesture_update(&gt, 100, true, true);

    // Hold through 1000ms, 2000ms, 2900ms
    gesture_event_t ev = gesture_update(&gt, 1000, true, true);
    assert(ev != GESTURE_EVENT_COMBO_LONG_SETUP && ev != GESTURE_EVENT_COMBO_SHORT);

    ev = gesture_update(&gt, 2000, true, true);
    assert(ev != GESTURE_EVENT_COMBO_LONG_SETUP && ev != GESTURE_EVENT_COMBO_SHORT);

    ev = gesture_update(&gt, 3000, true, true);
    assert(ev != GESTURE_EVENT_COMBO_LONG_SETUP && ev != GESTURE_EVENT_COMBO_SHORT);

    // At t=3100ms (held 3000ms): must trigger GESTURE_EVENT_COMBO_LONG_SETUP
    ev = gesture_update(&gt, 3100, true, true);
    assert(ev == GESTURE_EVENT_COMBO_LONG_SETUP);

    // Released at t=3500ms: must NOT trigger GESTURE_EVENT_COMBO_SHORT
    ev = gesture_update(&gt, 3500, false, false);
    assert(ev == GESTURE_EVENT_NONE);
    printf("PASS: test_long_hold_wifi_setup\n");
}

static void test_release_before_3s_no_wifi(void)
{
    gesture_tracker_t gt;
    gesture_init(&gt);

    gesture_update(&gt, 100, true, true);
    gesture_update(&gt, 1500, true, true);
    gesture_update(&gt, 2800, true, true); // 2700ms held

    // Released at 2850ms
    gesture_event_t ev = gesture_update(&gt, 2850, false, false);
    assert(ev == GESTURE_EVENT_COMBO_SHORT);
    printf("PASS: test_release_before_3s_no_wifi\n");
}

static void test_staggered_press_within_threshold(void)
{
    gesture_tracker_t gt;
    gesture_init(&gt);

    // B1 pressed at t=100ms
    gesture_event_t ev = gesture_update(&gt, 100, true, false);
    assert(ev == GESTURE_EVENT_NONE);

    // B2 pressed at t=250ms (diff = 150ms <= 250ms threshold)
    ev = gesture_update(&gt, 250, true, true);
    assert(ev == GESTURE_EVENT_HOLDING_SETUP);

    // Both held at t=500ms
    ev = gesture_update(&gt, 500, true, true);
    assert(ev != GESTURE_EVENT_SINGLE_ACCEPT && ev != GESTURE_EVENT_SINGLE_CANCEL);

    // Both released at t=700ms
    ev = gesture_update(&gt, 700, false, false);
    assert(ev == GESTURE_EVENT_COMBO_SHORT);
    printf("PASS: test_staggered_press_within_threshold\n");
}

static void test_staggered_press_exceeding_threshold(void)
{
    gesture_tracker_t gt;
    gesture_init(&gt);

    // B1 pressed at t=100ms
    gesture_event_t ev = gesture_update(&gt, 100, true, false);
    assert(ev == GESTURE_EVENT_NONE);

    // 260ms passes (now t=360ms), B2 still not pressed
    ev = gesture_update(&gt, 360, true, false);
    assert(ev == GESTURE_EVENT_SINGLE_ACCEPT);

    // Now B2 is pressed later at t=400ms: must NOT trigger dual combo!
    ev = gesture_update(&gt, 400, true, true);
    assert(ev == GESTURE_EVENT_NONE);

    // Both released: must NOT trigger combo short
    ev = gesture_update(&gt, 600, false, false);
    assert(ev == GESTURE_EVENT_NONE);
    printf("PASS: test_staggered_press_exceeding_threshold\n");
}

static void test_button_bounce_rejected(void)
{
    gesture_tracker_t gt;
    gesture_init(&gt);

    // B1 pressed at t=100ms
    gesture_update(&gt, 100, true, false);
    // B1 released at t=130ms (held only 30ms < 60ms debounce)
    gesture_event_t ev = gesture_update(&gt, 130, false, false);
    assert(ev == GESTURE_EVENT_NONE);
    printf("PASS: test_button_bounce_rejected\n");
}

static void test_single_accept_click(void)
{
    gesture_tracker_t gt;
    gesture_init(&gt);

    // B1 pressed at t=100ms
    gesture_update(&gt, 100, true, false);
    // B1 released at t=200ms (held 100ms >= 60ms debounce, <= 250ms sync)
    gesture_event_t ev = gesture_update(&gt, 200, false, false);
    assert(ev == GESTURE_EVENT_SINGLE_ACCEPT);
    printf("PASS: test_single_accept_click\n");
}

static void test_single_cancel_click(void)
{
    gesture_tracker_t gt;
    gesture_init(&gt);

    // B2 pressed at t=100ms
    gesture_update(&gt, 100, false, true);
    // B2 released at t=200ms
    gesture_event_t ev = gesture_update(&gt, 200, false, false);
    assert(ev == GESTURE_EVENT_SINGLE_CANCEL);
    printf("PASS: test_single_cancel_click\n");
}

static void test_held_keys_no_repeated_toggle(void)
{
    gesture_tracker_t gt;
    gesture_init(&gt);

    gesture_update(&gt, 100, true, true);
    // One button released at t=500ms
    gesture_event_t ev = gesture_update(&gt, 500, false, true);
    assert(ev == GESTURE_EVENT_COMBO_SHORT);

    // User keeps holding button 2 for another 2 seconds
    ev = gesture_update(&gt, 1000, false, true);
    assert(ev == GESTURE_EVENT_NONE);
    ev = gesture_update(&gt, 2000, false, true);
    assert(ev == GESTURE_EVENT_NONE);

    // Finally releases button 2
    ev = gesture_update(&gt, 2500, false, false);
    assert(ev == GESTURE_EVENT_NONE);
    printf("PASS: test_held_keys_no_repeated_toggle\n");
}

int main(void)
{
    printf("Running firmware host gesture tests...\n");
    test_clean_short_combo();
    test_long_hold_wifi_setup();
    test_release_before_3s_no_wifi();
    test_staggered_press_within_threshold();
    test_staggered_press_exceeding_threshold();
    test_button_bounce_rejected();
    test_single_accept_click();
    test_single_cancel_click();
    test_held_keys_no_repeated_toggle();
    printf("All 9 firmware gesture host tests PASSED!\n");
    return 0;
}
