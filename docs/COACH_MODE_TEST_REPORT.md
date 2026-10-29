# GAP-AI Coach Mode, Dual-Mode Gesture & Voice Reliability Test Report

**Target Branch:** `feat/esp32-coach-mode`
**Base Commit / Tag:** `604fab3eba5f4a6f1676862762e7fa9aafecb3eb` (`v1.2.0`)
**Target PR Base:** `main`
**Execution Date:** 2026-10-29

---

## 1. Executive Summary

This report documents the verification of the GAP-AI dual-mode voice assistant on ESP32 and Backend:
1. **Plan Mode:** Full multi-turn conversation, intelligent duration/time clarification, structured confirmation summary, and atomic plan persistence upon explicit confirmation ("Right.", "Yes", or Button 1).
2. **Coach Mode:** Seamless connection to the existing personalized recommendation engine (`apply_policy`, `calculate_recommendations`, `build_contextual_recommendations`). Spoken using a verified male voice (`troy` on Groq, `am_adam` on TTS.ai fallback). Supports user feedback (`dismissed` / `accepted`), date/time adjustments, and cycling without duplicate reading.
3. **Dual-Button Gesture State Machine:** Simultaneous Button 1 + Button 2 short press (<3s) toggles between Plan Mode and Coach Mode with spoken audio confirmation. Holding both for >=3s reliably opens the existing Wi-Fi setup portal (`portal_start()`) without accidental mode toggling. Staggered threshold (250ms) and 60ms debounce prevent false triggers.
4. **Firmware Audio Reliability & Button Lockout Fix:** Replaced the legacy fixed 768 KB audio buffer (`MAX_REPLY_WAV_BYTES`) in `play_wav_stream` with a chunked streaming reader directly to I2S. Polling accept/cancel buttons during chunked playback allows instant interruption, eliminating button lockout during long speech playback.

---

## 2. Root Cause Analysis & Technical Solutions

| Issue | Root Cause | Implemented Solution |
| :--- | :--- | :--- |
| **Audio Truncation (Ses Kesilmesi)** | Fixed 768 KB buffer (`MAX_REPLY_WAV_BYTES = 768 * 1024`) in `esp32/main/voice.c` truncated any WAV longer than ~16.3s at 24 kHz 16-bit mono. | Implemented streaming HTTP-to-I2S chunked playback (`audio_play_write`) directly from `esp_http_client_read`. Supports arbitrary audio length with zero PSRAM buffer overflow. |
| **Button Lockout During Playback** | Synchronous blocking audio read loop did not poll GPIO pins during audio output. | Added non-blocking button state checks (`voice_accept_button_pressed()`, `voice_cancel_button_pressed()`) in each 20ms audio chunk; immediately aborts playback to process user action. |
| **Pending Plan Proposal Lost** | Intervening queries like `"Do I have pending plans?"` triggered LLM classification that cleared or overrode the pending session context. | Implemented `is_pending_plan_query()` in `ConversationEngine` to recognize informational status inquiries, preserve the pending proposal ID, and remind the user of the pending summary without re-prompting. |
| **Malformed Plan Titles** | Substring patterns like `"go for a walk"` were greedily parsed into generic activities (`"Create a plan to activity today"`). | Enhanced `_fallback_extract` and LLM parsing prompts to preserve specific activity verbs ("Walk", "Run", "Study Math", "Swimming"). |
| **Repeated Confirmation Prompts** | Colloquial confirmation intents like `"Right."`, `"Right"`, or Turkish `"Onayla"` were not in `CONFIRMATION_PATTERNS`. | Expanded `CONFIRMATION_PATTERNS` in `backend/app/services/conversation.py` with `"right"`, `"right."`, `"thats right"`, `"all right"`, `"confirm it"`, `"onayla"`, `"evet"`, etc. |
| **Coach Mode Recommendation Engine Integration** | Voice assistant was previously disconnected from the web recommendation and insights engine. | Connected `ConversationEngine._refresh_recommendation_pool` directly to `apply_policy` from `app.recommendations` and `calculate_recommendations` from `app.analytics.insights`, sharing identical feedback and dismissal policies. |

---

## 3. Male TTS Voice Configuration

- **Groq Orpheus TTS:** Configured default `tts_coach_voice = "troy"` (verified male voice supported in Groq production).
- **TTS.ai Kokoro Fallback:** Configured fallback `tts_ai_coach_voice = "am_adam"` (verified male voice supported in TTS.ai).
- Verified in `backend/app/ai/tts.py` that `FallbackTTSClient` maps `"troy"` and `"austin"` directly to `"am_adam"` when falling back from Groq to TTS.ai.

---

## 4. Automated Verification Results

### 4.1 Host Unit Tests: Dual-Button Gesture State Machine
- **Test File:** `tests/firmware_host/test_gesture.c` + `esp32/main/gesture.c`
- **Compiler:** `gcc -Wall -Wextra -Iesp32/main`
- **Command:**
  ```bash
  gcc -Wall -Wextra -Iesp32/main tests/firmware_host/test_gesture.c esp32/main/gesture.c -o /tmp/test_gesture && /tmp/test_gesture
  ```
- **Output:**
  ```
  Running firmware host gesture tests...
  PASS: test_clean_short_combo
  PASS: test_long_hold_wifi_setup
  PASS: test_release_before_3s_no_wifi
  PASS: test_staggered_press_within_threshold
  PASS: test_staggered_press_exceeding_threshold
  PASS: test_button_bounce_rejected
  PASS: test_single_accept_click
  PASS: test_single_cancel_click
  PASS: test_held_keys_no_repeated_toggle
  All 9 firmware gesture host tests PASSED!
  ```

### 4.2 ESP-IDF Firmware Build
- **Target Chip:** ESP32-S3
- **Toolchain:** ESP-IDF v6.2 (xtensa-esp-elf)
- **Command:**
  ```bash
  bash -c "source /home/hamzamein-dev/esp/esp-idf/export.sh && cd esp32 && idf.py build"
  ```
- **Result:**
  ```
  gap_device.bin binary size 0x102980 bytes. Smallest app partition is 0x177000 bytes. 0x74680 bytes (31%) free.
  Project build complete.
  ```
- **Errors/Warnings:** 0 errors, 0 critical warnings.

### 4.3 Backend Test Suite (Pytest)
- **Command:**
  ```bash
  backend/.venv/bin/pytest backend/tests -q
  ```
- **Result:**
  ```
  531 passed, 1 warning in 44.48s
  ```
- **Targeted Coach & Voice Scenarios (`backend/tests/test_coach_mode_scenarios.py`):**
  1. `test_scenario_a_plan_mode_walk_confirmation`: PASSED
  2. `test_scenario_b_pending_plan_status_query_and_idempotency`: PASSED
  3. `test_scenario_c_coach_mode_recommendations_and_male_voice`: PASSED
  4. `test_scenario_d_convert_recommendation_to_plan`: PASSED
  5. `test_scenario_e_mode_announcement_endpoint`: PASSED

### 4.4 Web Frontend Test Suite (Node test runner)
- **Command:**
  ```bash
  cd web && npm test
  ```
- **Result:**
  ```
  ℹ tests 160
  ℹ suites 51
  ℹ pass 160
  ℹ fail 0
  ```

### 4.5 Git Integrity & Cleanliness Checks
- `git diff --check`: 0 whitespace or formatting errors.
- `git rev-parse v1.2.0^{commit}`: `604fab3eba5f4a6f1676862762e7fa9aafecb3eb` (Unchanged).

---

## 5. Test Environment & Hardware Status

> [!IMPORTANT]
> **Distinction Between Host Tests and Physical Hardware:**
> - The dual-button gesture state machine was strictly validated via **host unit test simulation** (`tests/firmware_host/test_gesture.c`), verifying debounce, staggered presses (250ms), hold threshold (3000ms), and single-trigger guarantees.
> - The firmware binary `gap_device.bin` compiled and linked cleanly with ESP-IDF v6.2 targeting ESP32-S3.
> - Final physical button tactile feel, acoustic microphone quality in noisy physical rooms, and physical speaker frequency response require on-device bench testing with physical hardware attached.
