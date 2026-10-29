#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <string.h>

#include "../../esp32/main/audio_feedback.h"

// Forward declarations of host test mock helpers in audio_feedback.c
void audio_feedback_mock_set_time(int64_t now_ms);
audio_feedback_event_t audio_feedback_mock_get_last_played(void);
uint32_t audio_feedback_mock_get_play_count(void);

// Test 1: Verify event priorities and human-readable names
static void test_event_priorities_and_names(void)
{
    audio_feedback_init();

    assert(audio_feedback_get_priority(AUDIO_FEEDBACK_NONE) == AUDIO_PRIO_IDLE);
    assert(audio_feedback_get_priority(AUDIO_FEEDBACK_WIFI_CONNECTED) == AUDIO_PRIO_STATUS);
    assert(audio_feedback_get_priority(AUDIO_FEEDBACK_WIFI_DISCONNECTED) == AUDIO_PRIO_STATUS);
    assert(audio_feedback_get_priority(AUDIO_FEEDBACK_BACKEND_CONNECTED) == AUDIO_PRIO_STATUS);
    assert(audio_feedback_get_priority(AUDIO_FEEDBACK_BACKEND_UNAVAILABLE) == AUDIO_PRIO_STATUS);

    assert(audio_feedback_get_priority(AUDIO_FEEDBACK_PTT_START) == AUDIO_PRIO_USER_ACTION);
    assert(audio_feedback_get_priority(AUDIO_FEEDBACK_RECORDING_SUBMITTED) == AUDIO_PRIO_USER_ACTION);
    assert(audio_feedback_get_priority(AUDIO_FEEDBACK_OPERATION_SUCCESS) == AUDIO_PRIO_USER_ACTION);
    assert(audio_feedback_get_priority(AUDIO_FEEDBACK_OPERATION_ERROR) == AUDIO_PRIO_USER_ACTION);
    assert(audio_feedback_get_priority(AUDIO_FEEDBACK_MODE_PLAN) == AUDIO_PRIO_USER_ACTION);
    assert(audio_feedback_get_priority(AUDIO_FEEDBACK_MODE_COACH) == AUDIO_PRIO_USER_ACTION);

    assert(strcmp(audio_feedback_get_name(AUDIO_FEEDBACK_PTT_START), "PTT_START") == 0);
    assert(strcmp(audio_feedback_get_name(AUDIO_FEEDBACK_RECORDING_SUBMITTED), "RECORDING_SUBMITTED") == 0);
    assert(strcmp(audio_feedback_get_name(AUDIO_FEEDBACK_WIFI_CONNECTED), "WIFI_CONNECTED") == 0);
    assert(strcmp(audio_feedback_get_name(AUDIO_FEEDBACK_BACKEND_CONNECTED), "BACKEND_CONNECTED") == 0);

    printf("PASS: test_event_priorities_and_names\n");
}

// Test 2: Speech playback suppression rule
// Routine events must NEVER interrupt spoken responses!
static void test_speech_active_suppression(void)
{
    audio_feedback_init();
    audio_feedback_mock_set_time(1000);

    // Initial state: speech inactive -> WiFi connected plays
    bool ok = audio_feedback_play(AUDIO_FEEDBACK_WIFI_CONNECTED);
    assert(ok == true);
    assert(audio_feedback_mock_get_last_played() == AUDIO_FEEDBACK_WIFI_CONNECTED);

    // Now speech becomes active (e.g. streaming WAV)
    audio_feedback_set_speech_active(true);
    assert(audio_feedback_is_speech_active() == true);

    audio_feedback_mock_set_time(6000);

    // Attempting to play status sounds while speech is active must be SUPPRESSED
    bool suppressed_wifi = audio_feedback_play(AUDIO_FEEDBACK_WIFI_DISCONNECTED);
    assert(suppressed_wifi == false);

    bool suppressed_backend = audio_feedback_play(AUDIO_FEEDBACK_BACKEND_CONNECTED);
    assert(suppressed_backend == false);

    // Speech finishes
    audio_feedback_set_speech_active(false);
    assert(audio_feedback_is_speech_active() == false);

    audio_feedback_mock_set_time(12000);
    bool allowed = audio_feedback_play(AUDIO_FEEDBACK_BACKEND_CONNECTED);
    assert(allowed == true);
    assert(audio_feedback_mock_get_last_played() == AUDIO_FEEDBACK_BACKEND_CONNECTED);

    printf("PASS: test_speech_active_suppression\n");
}

// Test 3: Plan proposal pending suppression rule
// Background network events must not distract while user is asked to accept/cancel plan
static void test_proposal_pending_suppression(void)
{
    audio_feedback_init();
    audio_feedback_mock_set_time(1000);

    audio_feedback_set_proposal_pending(true);
    assert(audio_feedback_is_proposal_pending() == true);

    // Status sounds suppressed
    bool suppressed = audio_feedback_play(AUDIO_FEEDBACK_WIFI_CONNECTED);
    assert(suppressed == false);

    // User action sounds (like button accept/cancel or error) still work
    bool action_ok = audio_feedback_play(AUDIO_FEEDBACK_OPERATION_SUCCESS);
    assert(action_ok == true);

    audio_feedback_set_proposal_pending(false);
    audio_feedback_mock_set_time(7000);
    bool status_now_ok = audio_feedback_play(AUDIO_FEEDBACK_WIFI_CONNECTED);
    assert(status_now_ok == true);

    printf("PASS: test_proposal_pending_suppression\n");
}

// Test 4: Debouncing & rate-limiting rule
// Repeated status events must not flood the speaker
static void test_debouncing_rate_limiting(void)
{
    audio_feedback_init();
    audio_feedback_mock_set_time(1000);

    // First trigger plays
    bool t1 = audio_feedback_play(AUDIO_FEEDBACK_BACKEND_UNAVAILABLE);
    assert(t1 == true);
    uint32_t count1 = audio_feedback_mock_get_play_count();

    // Rapid second trigger at +500 ms (< 4000 ms debounce) must be rejected
    audio_feedback_mock_set_time(1500);
    bool t2 = audio_feedback_play(AUDIO_FEEDBACK_BACKEND_UNAVAILABLE);
    assert(t2 == false);
    assert(audio_feedback_mock_get_play_count() == count1);

    // Trigger at +2000 ms (< 4000 ms debounce) must also be rejected
    audio_feedback_mock_set_time(3000);
    bool t3 = audio_feedback_play(AUDIO_FEEDBACK_BACKEND_UNAVAILABLE);
    assert(t3 == false);
    assert(audio_feedback_mock_get_play_count() == count1);

    // After debounce interval (+5000 ms > 4000 ms), it must play
    audio_feedback_mock_set_time(5500);
    bool t4 = audio_feedback_play(AUDIO_FEEDBACK_BACKEND_UNAVAILABLE);
    assert(t4 == true);
    assert(audio_feedback_mock_get_play_count() == count1 + 1);

    printf("PASS: test_debouncing_rate_limiting\n");
}

// Test 5: PTT activation and submission cues
static void test_ptt_interaction_cues(void)
{
    audio_feedback_init();
    audio_feedback_mock_set_time(1000);

    // Push button
    bool ptt_start = audio_feedback_play(AUDIO_FEEDBACK_PTT_START);
    assert(ptt_start == true);
    assert(audio_feedback_mock_get_last_played() == AUDIO_FEEDBACK_PTT_START);

    audio_feedback_mock_set_time(2500);

    // Release button (dispatch/send)
    bool ptt_submit = audio_feedback_play(AUDIO_FEEDBACK_RECORDING_SUBMITTED);
    assert(ptt_submit == true);
    assert(audio_feedback_mock_get_last_played() == AUDIO_FEEDBACK_RECORDING_SUBMITTED);

    printf("PASS: test_ptt_interaction_cues\n");
}

// Test 6: Mode change cues
static void test_mode_change_cues(void)
{
    audio_feedback_init();
    audio_feedback_mock_set_time(1000);

    bool plan_cue = audio_feedback_play(AUDIO_FEEDBACK_MODE_PLAN);
    assert(plan_cue == true);
    assert(audio_feedback_mock_get_last_played() == AUDIO_FEEDBACK_MODE_PLAN);

    audio_feedback_mock_set_time(1500);

    bool coach_cue = audio_feedback_play(AUDIO_FEEDBACK_MODE_COACH);
    assert(coach_cue == true);
    assert(audio_feedback_mock_get_last_played() == AUDIO_FEEDBACK_MODE_COACH);

    printf("PASS: test_mode_change_cues\n");
}

int main(void)
{
    printf("Running firmware host audio feedback unit tests...\n");
    test_event_priorities_and_names();
    test_speech_active_suppression();
    test_proposal_pending_suppression();
    test_debouncing_rate_limiting();
    test_ptt_interaction_cues();
    test_mode_change_cues();
    printf("All 6 audio feedback host tests PASSED successfully!\n");
    return 0;
}
