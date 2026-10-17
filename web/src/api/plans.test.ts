import assert from 'node:assert';
import { describe, it } from 'node:test';
import {
  createPlan,
  getLocalCurrentDate,
  mockParsePlan,
  mockSavePlan,
  parseNaturalLanguagePlan,
} from './plans.ts';
import type { ParsedPlan } from '../types/plan.ts';
import { generateIdempotencyKey, isValidUUID } from '../utils/idempotency.ts';

describe('GAP-AI W1-2: Plan Flow & API Tests', () => {
  describe('Idempotency & Date Utilities', () => {
    it('generates a valid RFC 4122 v4 UUID', () => {
      const key1 = generateIdempotencyKey();
      const key2 = generateIdempotencyKey();

      assert.ok(isValidUUID(key1), `Expected valid UUID, got: ${key1}`);
      assert.ok(isValidUUID(key2), `Expected valid UUID, got: ${key2}`);
      assert.notStrictEqual(key1, key2, 'Generated keys must be distinct');
    });

    it('rejects invalid UUID strings', () => {
      assert.strictEqual(isValidUUID(''), false);
      assert.strictEqual(isValidUUID('invalid-uuid'), false);
      assert.strictEqual(isValidUUID('12345'), false);
      assert.strictEqual(
        isValidUUID('550e8400-e29b-41d4-a716-44665544000z'),
        false
      );
    });

    it('formats current date in YYYY-MM-DD pattern', () => {
      const today = getLocalCurrentDate();
      assert.match(
        today,
        /^\d{4}-\d{2}-\d{2}$/,
        'Date must match YYYY-MM-DD pattern'
      );
    });
  });

  describe('parseNaturalLanguagePlan Validation & Error Handling', () => {
    it('rejects empty input without calling backend', async () => {
      await assert.rejects(
        async () => {
          await parseNaturalLanguagePlan('   ');
        },
        {
          name: 'ApiError',
          status: 422,
          errorType: 'validation_error',
        }
      );
    });

    it('parses text into create_plan in mock mode', async () => {
      const result = await parseNaturalLanguagePlan(
        "Yarın saat 18:00'de Belgrad Ormanı'nda 1 saat koşu yapacağım.",
        { mockMode: true }
      );

      assert.strictEqual(result.intent, 'create_plan');
      assert.strictEqual(result.title, 'Koşu');
      assert.strictEqual(result.category, 'sport');
      assert.strictEqual(result.time, '18:00');
      assert.strictEqual(result.duration_minutes, 60);
      assert.strictEqual(result.needs_weather_check, true);
      assert.strictEqual(result.clarification_question, null);
      assert.ok(result.confidence >= 0.85);
    });

    it('triggers clarify intent when essential time information is missing', async () => {
      const result = await parseNaturalLanguagePlan('Yarın koşuya çıkacağım.', {
        mockMode: true,
      });

      assert.strictEqual(result.intent, 'clarify');
      assert.strictEqual(result.time, null);
      assert.strictEqual(typeof result.clarification_question, 'string');
      assert.ok(
        result.clarification_question &&
          result.clarification_question.length > 0
      );
    });

    it('triggers unsupported intent for general chit-chat and greetings', async () => {
      const result = await parseNaturalLanguagePlan('Merhaba, nasılsın?', {
        mockMode: true,
      });

      assert.strictEqual(result.intent, 'unsupported');
      assert.strictEqual(result.title, null);
      assert.strictEqual(result.category, null);
      assert.strictEqual(result.date, null);
      assert.strictEqual(result.time, null);
      assert.strictEqual(result.duration_minutes, null);
      assert.strictEqual(result.clarification_question, null);
      assert.strictEqual(result.needs_weather_check, false);
    });

    it('triggers unsupported intent for "Merhaba, bana bir fıkra anlat." and joke/chit-chat variations', async () => {
      const phrases = [
        'Merhaba, bana bir fıkra anlat.',
        'bana bir fıkra anlat',
        'bana bir fikra anlat',
        'Fıkra anlat',
        'fikra anlat',
        'şaka yap',
        'saka yap',
        'günaydın nasılsın',
        'sen kimsin',
      ];

      for (const phrase of phrases) {
        const result = await parseNaturalLanguagePlan(phrase, {
          mockMode: true,
        });

        assert.strictEqual(
          result.intent,
          'unsupported',
          `Expected unsupported for "${phrase}", got: ${result.intent}`
        );
        assert.strictEqual(result.title, null);
        assert.strictEqual(result.time, null);
        assert.strictEqual(result.needs_weather_check, false);
      }
    });
  });

  describe('Clarify Flow: Combination of Clarification Answers', () => {
    it('combines original prompt with clarification reply to produce create_plan', async () => {
      const originalPrompt = 'Yarın koşuya çıkacağım';
      const clarifyResult = mockParsePlan(originalPrompt);
      assert.strictEqual(clarifyResult.intent, 'clarify');

      const userReply = 'Saat 18:00';
      const combinedPrompt = `${originalPrompt}. ${userReply}`;

      const reparseResult = await parseNaturalLanguagePlan(combinedPrompt, {
        mockMode: true,
      });
      assert.strictEqual(reparseResult.intent, 'create_plan');
      assert.strictEqual(reparseResult.time, '18:00');
    });
  });

  describe('createPlan Validation & Idempotent Persistence', () => {
    const validParsedPlan: ParsedPlan = {
      intent: 'create_plan',
      title: 'Ders Çalışma',
      category: 'study',
      date: '2026-10-18',
      time: '14:00',
      duration_minutes: 90,
      recurrence: null,
      language: 'tr',
      needs_weather_check: false,
      clarification_question: null,
      confidence: 0.95,
    };

    it('rejects saving a plan whose intent is clarify', async () => {
      const clarifyPlan: ParsedPlan = {
        ...validParsedPlan,
        intent: 'clarify',
        clarification_question: 'Saat kaçta?',
      };
      const key = generateIdempotencyKey();

      await assert.rejects(
        async () => {
          await createPlan(clarifyPlan, key, { mockMode: true });
        },
        {
          name: 'ApiError',
          status: 422,
          errorType: 'validation_error',
        }
      );
    });

    it('rejects saving a plan whose intent is unsupported', async () => {
      const unsupportedPlan: ParsedPlan = {
        ...validParsedPlan,
        intent: 'unsupported',
        title: null,
      };
      const key = generateIdempotencyKey();

      await assert.rejects(
        async () => {
          await createPlan(unsupportedPlan, key, { mockMode: true });
        },
        {
          name: 'ApiError',
          status: 422,
          errorType: 'validation_error',
        }
      );
    });

    it('rejects saving if Idempotency-Key is not a valid UUID', async () => {
      await assert.rejects(
        async () => {
          await createPlan(validParsedPlan, 'not-a-uuid', { mockMode: true });
        },
        {
          name: 'ApiError',
          status: 422,
          errorType: 'validation_error',
        }
      );
    });

    it('successfully saves a confirmed plan with valid UUID key in mock mode', async () => {
      const key = generateIdempotencyKey();
      const saved = await createPlan(validParsedPlan, key, { mockMode: true });

      assert.ok(isValidUUID(saved.id));
      assert.strictEqual(saved.title, 'Ders Çalışma');
      assert.strictEqual(saved.category, 'study');
      assert.strictEqual(saved.source, 'text');
      assert.ok(saved.planned_start.includes('2026-10-18T14:00:00'));
    });

    it('preserves the same idempotency key across multiple retry calls', async () => {
      const fixedKey = generateIdempotencyKey();
      const plan1 = mockSavePlan(validParsedPlan, fixedKey);
      const plan2 = mockSavePlan(validParsedPlan, fixedKey);

      assert.strictEqual(isValidUUID(fixedKey), true);
      assert.ok(plan1.id);
      assert.ok(plan2.id);
    });
  });

  describe('Live Contract & Strict Error Propagation (No Silent Fallback)', () => {
    const originalFetch = globalThis.fetch;

    it('sends strictly conforming payload to POST /parse and parses response', async () => {
      let capturedUrl = '';
      let capturedMethod = '';
      let capturedBody: Record<string, unknown> = {};

      globalThis.fetch = (async (url: string, init?: RequestInit) => {
        capturedUrl = url;
        capturedMethod = init?.method || '';
        capturedBody = JSON.parse((init?.body as string) || '{}');

        return new Response(
          JSON.stringify({
            intent: 'create_plan',
            title: 'Koşu',
            category: 'sport',
            date: '2026-10-18',
            time: '18:00',
            duration_minutes: 60,
            recurrence: null,
            language: 'tr',
            needs_weather_check: true,
            clarification_question: null,
            confidence: 0.96,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        const result = await parseNaturalLanguagePlan('Yarın 18:00 koşu', {
          mockMode: false,
          language: 'tr',
        });

        assert.strictEqual(capturedMethod, 'POST');
        assert.ok(capturedUrl.endsWith('/parse'));
        assert.strictEqual(capturedBody.text, 'Yarın 18:00 koşu');
        assert.strictEqual(capturedBody.language, 'tr');
        assert.match(
          capturedBody.current_date as string,
          /^\d{4}-\d{2}-\d{2}$/
        );
        // Ensure no unexpected extra fields are sent (avoiding extra="forbid" 422s)
        const allowedKeys = ['text', 'current_date', 'language'];
        for (const k of Object.keys(capturedBody)) {
          assert.ok(allowedKeys.includes(k), `Unexpected key in payload: ${k}`);
        }

        assert.strictEqual(result.intent, 'create_plan');
        assert.strictEqual(result.title, 'Koşu');
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('propagates 502 parse_failed from backend without silent mock fallback', async () => {
      globalThis.fetch = (async () => {
        return new Response(
          JSON.stringify({
            error: 'parse_failed',
            message: 'Model çıktısı doğrulanamadı.',
          }),
          { status: 502, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        await assert.rejects(
          async () => {
            await parseNaturalLanguagePlan('Karmaşık metin', {
              mockMode: false,
            });
          },
          {
            name: 'ApiError',
            status: 502,
            errorType: 'parse_failed',
            message: 'Model çıktısı doğrulanamadı.',
          }
        );
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('propagates 503 llm_unavailable from backend without silent mock fallback', async () => {
      globalThis.fetch = (async () => {
        return new Response(
          JSON.stringify({
            error: 'llm_unavailable',
            message: 'Model sağlayıcısına ulaşılamıyor.',
          }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        await assert.rejects(
          async () => {
            await parseNaturalLanguagePlan('Yarın koşu', { mockMode: false });
          },
          {
            name: 'ApiError',
            status: 503,
            errorType: 'llm_unavailable',
          }
        );
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('sends Idempotency-Key and source in POST /plans', async () => {
      let capturedHeaders: HeadersInit = {};
      let capturedBody: Record<string, unknown> = {};

      globalThis.fetch = (async (_url: string, init?: RequestInit) => {
        capturedHeaders = init?.headers || {};
        capturedBody = JSON.parse((init?.body as string) || '{}');

        return new Response(
          JSON.stringify({
            id: '123e4567-e89b-12d3-a456-426614174000',
            title: 'Ders Çalışma',
            category: 'study',
            planned_start: '2026-10-18T14:00:00+03:00',
            planned_end: '2026-10-18T15:30:00+03:00',
            recurrence_rule: null,
            source: 'text',
            created_at: '2026-10-17T12:00:00+03:00',
            latest_outcome: null,
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        const key = generateIdempotencyKey();
        const saved = await createPlan(
          {
            intent: 'create_plan',
            title: 'Ders Çalışma',
            category: 'study',
            date: '2026-10-18',
            time: '14:00',
            duration_minutes: 90,
            recurrence: null,
            language: 'tr',
            needs_weather_check: false,
            clarification_question: null,
            confidence: 0.95,
          },
          key,
          { mockMode: false }
        );

        const headers = new Headers(capturedHeaders);
        assert.strictEqual(headers.get('Idempotency-Key'), key);
        assert.strictEqual(capturedBody.source, 'text');
        assert.ok(capturedBody.parsed_plan);
        assert.strictEqual(saved.id, '123e4567-e89b-12d3-a456-426614174000');
      } finally {
        globalThis.fetch = originalFetch;
      }
    });
  });
});
