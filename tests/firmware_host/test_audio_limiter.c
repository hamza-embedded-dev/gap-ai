#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <math.h>

#include "../../esp32/main/audio_limiter.h"

// Test 1: Verify default scale and initialization parameters
static void test_default_scale_and_init(void)
{
    audio_limiter_t lim;
    audio_limiter_init(&lim, AUDIO_LIMITER_DEFAULT_SCALE, 16000);

    assert(fabsf(audio_limiter_get_scale(&lim) - 0.35f) < 0.001f);
    assert(lim.sample_rate == 16000);
    assert(lim.high_pass_hz == 250.0f);
    assert(lim.hp_alpha > 0.0f && lim.hp_alpha < 1.0f);
    printf("PASS: test_default_scale_and_init\n");
}

// Test 2: Bounding of maximum positive full-scale PCM samples (+32767)
static void test_positive_full_scale_bounded(void)
{
    audio_limiter_t lim;
    audio_limiter_init(&lim, 0.35f, 16000);
    lim.fade_done = lim.fade_total; // bypass fade-in to test steady-state ceiling

    int16_t max_allowed = (int16_t)roundf(32767.0f * 0.35f); // 11468

    for (int i = 0; i < 500; i++) {
        int16_t out = audio_limiter_process_sample(&lim, 32767);
        assert(out <= max_allowed);
        assert(out >= -max_allowed);
    }
    printf("PASS: test_positive_full_scale_bounded (out <= %d)\n", max_allowed);
}

// Test 3: Bounding of maximum negative full-scale PCM samples (-32768)
static void test_negative_full_scale_bounded(void)
{
    audio_limiter_t lim;
    audio_limiter_init(&lim, 0.35f, 16000);
    lim.fade_done = lim.fade_total; // bypass fade-in

    int16_t max_allowed = (int16_t)roundf(32767.0f * 0.35f); // 11468

    for (int i = 0; i < 500; i++) {
        int16_t out = audio_limiter_process_sample(&lim, -32768);
        assert(out >= -max_allowed);
        assert(out <= max_allowed);
    }
    printf("PASS: test_negative_full_scale_bounded (out >= -%d)\n", max_allowed);
}

// Test 4: Maximum high-pass overshoot / square wave ringing test
// Alternating between +32767 and -32768 causes maximum derivative step input
static void test_alternating_square_wave_worst_case(void)
{
    audio_limiter_t lim;
    audio_limiter_init(&lim, 0.35f, 16000);
    lim.fade_done = lim.fade_total;

    int16_t max_allowed = (int16_t)roundf(32767.0f * 0.35f);

    for (int i = 0; i < 1000; i++) {
        int16_t in_val = (i % 2 == 0) ? 32767 : -32768;
        int16_t out_val = audio_limiter_process_sample(&lim, in_val);

        // Verify strict bounds without any integer overflow or wrapping
        assert(out_val <= max_allowed);
        assert(out_val >= -max_allowed);
    }
    printf("PASS: test_alternating_square_wave_worst_case (all in [-%d, +%d])\n",
           max_allowed, max_allowed);
}

// Test 5: Configurable scale levels (0.10, 0.20, 0.50, 0.0)
static void test_configurable_scales(void)
{
    audio_limiter_t lim;
    audio_limiter_init(&lim, 0.35f, 16000);
    lim.fade_done = lim.fade_total;

    float scales[] = {0.10f, 0.20f, 0.50f, 0.0f};
    for (size_t s = 0; s < sizeof(scales)/sizeof(scales[0]); s++) {
        audio_limiter_set_scale(&lim, scales[s]);
        int16_t expected_ceil = (int16_t)roundf(32767.0f * scales[s]);

        for (int i = 0; i < 200; i++) {
            int16_t out = audio_limiter_process_sample(&lim, 32767);
            assert(out <= expected_ceil);
            assert(out >= -expected_ceil);
        }
        if (scales[s] == 0.0f) {
            // Mute scale must produce 0
            int16_t out = audio_limiter_process_sample(&lim, 32767);
            assert(out == 0);
        }
    }
    printf("PASS: test_configurable_scales\n");
}

// Test 6: Safety clamping of out-of-range scale values
static void test_scale_clamping(void)
{
    audio_limiter_t lim;
    audio_limiter_init(&lim, 0.35f, 16000);

    audio_limiter_set_scale(&lim, -0.5f);
    assert(audio_limiter_get_scale(&lim) == 0.0f);

    audio_limiter_set_scale(&lim, 1.8f);
    assert(audio_limiter_get_scale(&lim) == 1.0f);

    audio_limiter_set_scale(&lim, 0.35f);
    assert(fabsf(audio_limiter_get_scale(&lim) - 0.35f) < 0.001f);
    printf("PASS: test_scale_clamping\n");
}

// Test 7: Simulated beep() generator path
static void test_beep_path_bounded(void)
{
    audio_limiter_t lim;
    audio_limiter_init(&lim, 0.35f, 16000);

    int16_t max_allowed = (int16_t)roundf(32767.0f * 0.35f);
    float hz = 1000.0f;

    // Simulate beep buffer with 10000 amplitude
    for (int i = 0; i < 320; i++) {
        int16_t raw_sine = (int16_t)(sinf(2.0f * (float)M_PI * hz * i / 16000.0f) * 10000.0f);
        int16_t out = audio_limiter_process_sample(&lim, raw_sine);
        assert(out <= max_allowed);
        assert(out >= -max_allowed);
    }
    printf("PASS: test_beep_path_bounded\n");
}

// Test 8: Stereo interleaving and sample alignment
static void test_stereo_interleaving(void)
{
    audio_limiter_t lim;
    audio_limiter_init(&lim, 0.35f, 16000);

    int16_t in_mono[128];
    int16_t out_stereo[256];

    for (int i = 0; i < 128; i++) {
        in_mono[i] = (int16_t)(i * 200 - 12000);
    }

    audio_limiter_process_stereo(&lim, in_mono, out_stereo, 128);

    for (int i = 0; i < 128; i++) {
        // Both left and right slots must receive identical bounded samples
        assert(out_stereo[2 * i] == out_stereo[2 * i + 1]);
        assert(out_stereo[2 * i] <= (int16_t)roundf(32767.0f * 0.35f));
        assert(out_stereo[2 * i] >= -(int16_t)roundf(32767.0f * 0.35f));
    }
    printf("PASS: test_stereo_interleaving\n");
}

// Test 9: Fade-in smooth startup prevents pop
static void test_fade_in_profile(void)
{
    audio_limiter_t lim;
    audio_limiter_init(&lim, 0.35f, 16000);

    int16_t prev_out = 0;
    // During the first few samples of fade-in, output envelope must be attenuated
    for (int i = 0; i < 20; i++) {
        int16_t out = audio_limiter_process_sample(&lim, 20000);
        if (i == 0) {
            // First sample should be close to 0 due to fade-in multiplier (0 / fade_total)
            assert(abs(out) <= 50);
        }
        prev_out = out;
        (void)prev_out;
    }
    printf("PASS: test_fade_in_profile\n");
}

int main(void)
{
    printf("Running firmware host audio limiter tests for 0.5W 8-ohm speaker protection...\n");
    test_default_scale_and_init();
    test_positive_full_scale_bounded();
    test_negative_full_scale_bounded();
    test_alternating_square_wave_worst_case();
    test_configurable_scales();
    test_scale_clamping();
    test_beep_path_bounded();
    test_stereo_interleaving();
    test_fade_in_profile();
    printf("All 9 audio limiter host tests PASSED successfully!\n");
    return 0;
}
