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
5. **Speaker Rating & Digital Volume Limiter:** Corrected hardware speaker specification to **0.5 W, 8 Ohm** (not 3 W). Implemented a centralized, configurable digital volume limiter (`audio_limiter.c`) with a conservative default scale of 0.35 across all audio paths (streamed TTS, beeps, announcements, startup cues). Eliminated high-level sustained tones.

---

## 2. Root Cause Analysis & Technical Solutions

| Issue | Root Cause | Implemented Solution |
| :--- | :--- | :--- |
| **Speaker Power Mismatch (0.5 W, 8 Ohm)** | MAX98357A Class D amplifier with 5V VIN and 9 dB gain can deliver up to ~1.56 W into 8 Ohm, exceeding the small 0.5 W speaker's thermal/mechanical power limit. | Implemented `audio_limiter` module applying high-pass voice-coil protection (250 Hz cutoff), smooth fade-in, and configurable digital attenuation (default 0.35x = -9.1 dBFS). Protects all speaker output paths including streamed TTS, beeps, and announcements. |
| **Sustained Boot Tone Risk** | Legacy `voice_speaker_test()` ran a 1000 Hz tone at 12000 amplitude for 1 full second (1000 ms), risking voice-coil overheating. | Replaced with a gentle, brief 70 ms 440 Hz cue at conservative amplitude through the limiter. All system beeps are bounded to <= 80 ms. |
| **Audio Truncation (Ses Kesilmesi)** | Fixed 768 KB buffer (`MAX_REPLY_WAV_BYTES = 768 * 1024`) in `esp32/main/voice.c` truncated any WAV longer than ~16.3s at 24 kHz 16-bit mono. | Implemented streaming HTTP-to-I2S chunked playback (`audio_play_write`) directly from `esp_http_client_read`. Supports arbitrary audio length with zero PSRAM buffer overflow. |
| **Button Lockout During Playback** | Synchronous blocking audio read loop did not poll GPIO pins during audio output. | Added non-blocking button state checks (`voice_accept_button_pressed()`, `voice_cancel_button_pressed()`) in each 20ms audio chunk; immediately aborts playback to process user action. |
| **Pending Plan Proposal Lost** | Intervening queries like `"Do I have pending plans?"` triggered LLM classification that cleared or overrode the pending session context. | Implemented `is_pending_plan_query()` in `ConversationEngine` to recognize informational status inquiries, preserve the pending proposal ID, and remind the user of the pending summary without re-prompting. |
| **Malformed Plan Titles** | Substring patterns like `"go for a walk"` were greedily parsed into generic activities (`"Create a plan to activity today"`). | Enhanced `_fallback_extract` and LLM parsing prompts to preserve specific activity verbs ("Walk", "Run", "Study Math", "Swimming"). |
| **Repeated Confirmation Prompts** | Colloquial confirmation intents like `"Right."`, `"Right"`, or Turkish `"Onayla"` were not in `CONFIRMATION_PATTERNS`. | Expanded `CONFIRMATION_PATTERNS` in `backend/app/services/conversation.py` with `"right"`, `"right."`, `"thats right"`, `"all right"`, `"confirm it"`, `"onayla"`, `"evet"`, etc. |
| **Coach Mode Recommendation Engine Integration** | Voice assistant was previously disconnected from the web recommendation and insights engine. | Connected `ConversationEngine._refresh_recommendation_pool` directly to `apply_policy` from `app.recommendations` and `calculate_recommendations` from `app.analytics.insights`, sharing identical feedback and dismissal policies. |

---

## 3. Hardware Inspection & Digital Volume Limiter

### 3.1 Amplifier Board Wiring & Gain Configuration
- **Amplifier IC:** Maxim Integrated MAX98357A (mono I2S Class D DAC/Amp).
- **Supply Voltage (VIN):** 5V rail from development board header.
- **Hardware GAIN Pin:** **Unconnected (floating)**, configuring internal 9 dB voltage gain (~2.82 V/V) as defined in `esp32/main/board_pins.h`.
- **Connected Speaker:** **0.5 W rated power, 8 Ohm nominal impedance**.
- **Power Analysis:**
  $$\text{At } V_{supply} = 5.0\text{V, } P_{max} \approx \frac{(5.0 / \sqrt{2})^2}{8} \approx 1.56\text{ W RMS into 8 }\Omega$$
  Full scale 0 dBFS unattenuated digital audio would exceed the 0.5 W rating by more than 3x.
- **Digital Volume Limiter (`esp32/main/audio_limiter.c`):**
  - Starting attenuation factor: `AUDIO_LIMITER_DEFAULT_SCALE = 0.35f` (-9.1 dBFS).
  - Runtime configurable: `audio_play_set_volume_limit(float)` / `audio_play_get_volume_limit()`.
  - Power reduction: $0.35^2 \approx 0.1225$ (> 8x electrical power reduction relative to full scale for equivalent waveform).
  - Clamping: Strict ceiling $32767 \times \text{scale}$ prevents digital clipping or arithmetic overflow.
  - High-pass voice-coil filter: 1-pole high-pass at 250 Hz filters out sub-bass frequencies that small 0.5 W drivers cannot acoustically reproduce.

> [!WARNING]
> **Electrical Power Disclaimer:**
> Digital scaling is a conservative starting attenuation value, **NOT a guaranteed 0.5 W physical power limit**. Exact electrical and acoustic power delivered to the speaker depends on:
> 1. Power supply rail voltage and impedance (e.g. 5V USB rail droop).
> 2. Physical GAIN pin connection (floating vs tied to GND/VIN).
> 3. Speaker impedance curve across frequency (nominal 8 Ohm, but varies with resonance).
> 4. Audio signal crest factor and spectral distribution.
> Physical oscilloscope or true-RMS voltmeter measurement across speaker terminals during playback is required to verify actual wattage in a physical lab environment.

---

## 4. Male TTS Voice Configuration

- **Groq Orpheus TTS:** Configured default `tts_coach_voice = "troy"` (verified male voice supported in Groq production).
- **TTS.ai Kokoro Fallback:** Configured fallback `tts_ai_coach_voice = "am_adam"` (verified male voice supported in TTS.ai).
- Verified in `backend/app/ai/tts.py` that `FallbackTTSClient` maps `"troy"` and `"austin"` directly to `"am_adam"` when falling back from Groq to TTS.ai.

---

## 5. Automated Verification Results

### 5.1 Host Unit Tests: Digital Volume Limiter (0.5 W Speaker Protection)
- **Test File:** `tests/firmware_host/test_audio_limiter.c` + `esp32/main/audio_limiter.c`
- **Compiler:** `gcc -Wall -Wextra -Iesp32/main -lm`
- **Command:**
  ```bash
  gcc -Wall -Wextra -Iesp32/main tests/firmware_host/test_audio_limiter.c esp32/main/audio_limiter.c -lm -o /tmp/test_audio_limiter && /tmp/test_audio_limiter
  ```
- **Output:**
  ```
  Running firmware host audio limiter tests for 0.5W 8-ohm speaker protection...
  PASS: test_default_scale_and_init
  PASS: test_positive_full_scale_bounded (out <= 11468)
  PASS: test_negative_full_scale_bounded (out >= -11468)
  PASS: test_alternating_square_wave_worst_case (all in [-11468, +11468])
  PASS: test_configurable_scales
  PASS: test_scale_clamping
  PASS: test_beep_path_bounded
  PASS: test_stereo_interleaving
  PASS: test_fade_in_profile
  All 9 audio limiter host tests PASSED successfully!
  ```

### 5.2 Host Unit Tests: Dual-Button Gesture State Machine
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

### 5.3 ESP-IDF Firmware Build
- **Target Chip:** ESP32-S3
- **Toolchain:** ESP-IDF v6.2 (xtensa-esp-elf)
- **Command:**
  ```bash
  bash -c "source /home/hamzamein-dev/esp/esp-idf/export.sh && cd esp32 && idf.py build"
  ```
- **Result:**
  ```
  gap_device.bin binary size 0x102af0 bytes. Smallest app partition is 0x177000 bytes. 0x74510 bytes (31%) free.
  Project build complete.
  ```
- **Errors/Warnings:** 0 errors, 0 critical warnings.

### 5.4 Backend Test Suite (Pytest)
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

### 5.5 Web Frontend Test Suite (Node test runner)
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

### 5.6 Git Integrity & Cleanliness Checks
- `git diff --check`: 0 whitespace or formatting errors.
- `git rev-parse v1.2.0^{commit}`: `604fab3eba5f4a6f1676862762e7fa9aafecb3eb` (Unchanged).

---

## 6. Test Environment & Physical Hardware Status

> [!IMPORTANT]
> **Distinction Between Host Tests and Physical Hardware:**
> - Both the dual-button gesture state machine and the audio volume limiter were strictly validated via **host unit test simulation** (`test_gesture.c` 9/9 passed, `test_audio_limiter.c` 9/9 passed).
> - Firmware binary `gap_device.bin` compiled and linked cleanly with ESP-IDF v6.2.
> - **On-Device Bench Testing Remaining:**
>   1. Electrical output voltage measurement across the 8 Ohm speaker terminals with an oscilloscope/multimeter under live playback to verify power levels.
>   2. Audio distortion and perceptual loudness check at low starting volume (scale 0.35).
>   3. Physical button tactile feel and dual-button combo ergonomics.
>   4. Acoustic microphone response in real-room reverberant conditions.
