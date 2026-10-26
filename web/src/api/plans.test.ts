import assert from 'node:assert';
import { describe, it } from 'node:test';
import { apiFetch, ApiError } from './client.ts';
import {
  createPlan,
  deletePlan,
  getLocalCurrentDate,
  listPlans,
  mockListPlans,
  mockParsePlan,
  mockReportPlanOutcome,
  mockSavePlan,
  parseNaturalLanguagePlan,
  reportPlanOutcome,
  validatePlanForCreation,
  validatePlanForUpdate,
  formatOutcomeTime,
  updatePlan,
} from './plans.ts';
import type { ParsedPlan, Plan, PlanOutcome } from '../types/plan.ts';
import { generateIdempotencyKey, isValidUUID } from '../utils/idempotency.ts';
import {
  countActivePlanFilters,
  DEFAULT_PLAN_FILTERS,
  getPlanCategories,
  sortAndFilterPlans,
  type PlanFilters,
} from '../utils/planFilters.ts';


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

describe('Plan sorting and filtering', () => {
  const atLocalTime = (year: number, month: number, day: number, hour = 12) =>
    new Date(year, month, day, hour, 0, 0).toISOString();

  function makePlan(id: string, changes: Partial<Plan> & { description?: string } = {}): Plan {
    const { description, ...planChanges } = changes;
    return {
      id,
      title: id,
      category: 'work',
      planned_start: atLocalTime(2026, 9, 26, 18),
      planned_end: atLocalTime(2026, 9, 26, 19),
      recurrence_rule: null,
      source: 'text',
      created_at: atLocalTime(2026, 9, 25),
      latest_outcome: null,
      ...planChanges,
      ...(description ? { description } : {}),
    } as Plan;
  }

  const ids = (items: Plan[]) => items.map((item) => item.id);
  const now = new Date(2026, 9, 26, 12, 0, 0);

  it('sorts newest and oldest creation dates in the requested directions', () => {
    const items = [
      makePlan('middle', { created_at: atLocalTime(2026, 9, 24) }),
      makePlan('newest', { created_at: atLocalTime(2026, 9, 26) }),
      makePlan('oldest', { created_at: atLocalTime(2026, 9, 22) }),
    ];
    assert.deepStrictEqual(ids(sortAndFilterPlans(items, DEFAULT_PLAN_FILTERS, 'created_newest', now)), ['newest', 'middle', 'oldest']);
    assert.deepStrictEqual(ids(sortAndFilterPlans(items, DEFAULT_PLAN_FILTERS, 'created_oldest', now)), ['oldest', 'middle', 'newest']);
  });

  it('sorts plan dates both ways, keeps undated plans last and breaks ties by newest creation', () => {
    const items = [
      makePlan('undated', { planned_start: null as unknown as string }),
      makePlan('far', { planned_start: atLocalTime(2026, 10, 2) }),
      makePlan('tie-old', { planned_start: atLocalTime(2026, 9, 27), created_at: atLocalTime(2026, 9, 20) }),
      makePlan('near', { planned_start: atLocalTime(2026, 9, 26, 13) }),
      makePlan('tie-new', { planned_start: atLocalTime(2026, 9, 27), created_at: atLocalTime(2026, 9, 25) }),
    ];
    assert.deepStrictEqual(ids(sortAndFilterPlans(items, DEFAULT_PLAN_FILTERS, 'start_nearest', now)), ['near', 'tie-new', 'tie-old', 'far', 'undated']);
    assert.deepStrictEqual(ids(sortAndFilterPlans(items, DEFAULT_PLAN_FILTERS, 'start_farthest', now)), ['far', 'tie-new', 'tie-old', 'near', 'undated']);
  });

  it('maps pending to no outcome and status filters to persisted outcome statuses', () => {
    const items = [
      makePlan('pending'),
      makePlan('done', { latest_outcome: { id: 'o1', plan_id: 'done', status: 'done', actual_start: null, postponed_to: null, note: null, reported_via: 'web', reported_at: atLocalTime(2026, 9, 26) } }),
      makePlan('postponed', { latest_outcome: { id: 'o2', plan_id: 'postponed', status: 'postponed', actual_start: null, postponed_to: atLocalTime(2026, 9, 28), note: null, reported_via: 'web', reported_at: atLocalTime(2026, 9, 26) } }),
      makePlan('skipped', { latest_outcome: { id: 'o3', plan_id: 'skipped', status: 'skipped', actual_start: null, postponed_to: null, note: null, reported_via: 'web', reported_at: atLocalTime(2026, 9, 26) } }),
    ];
    for (const [status, id] of [['pending', 'pending'], ['done', 'done'], ['postponed', 'postponed'], ['skipped', 'skipped']] as Array<[PlanFilters['status'], string]>) {
      assert.deepStrictEqual(ids(sortAndFilterPlans(items, { ...DEFAULT_PLAN_FILTERS, status }, 'created_newest', now)), [id]);
    }
  });

  it('uses local day and Monday-based week boundaries for time filters', () => {
    const items = [
      makePlan('previous-week', { planned_start: atLocalTime(2026, 9, 25, 23) }),
      makePlan('today-past', { planned_start: atLocalTime(2026, 9, 26, 10) }),
      makePlan('today-future', { planned_start: atLocalTime(2026, 9, 26, 15) }),
      makePlan('tomorrow', { planned_start: atLocalTime(2026, 9, 27, 9) }),
      makePlan('weekend', { planned_start: atLocalTime(2026, 9, 31, 9) }),
      makePlan('next-week', { planned_start: atLocalTime(2026, 10, 2, 9) }),
    ];
    const filterTime = (time: PlanFilters['time']) => ids(sortAndFilterPlans(items, { ...DEFAULT_PLAN_FILTERS, time }, 'start_nearest', now));
    assert.deepStrictEqual(filterTime('today'), ['today-past', 'today-future']);
    assert.deepStrictEqual(filterTime('tomorrow'), ['tomorrow']);
    assert.deepStrictEqual(filterTime('this_week'), ['today-past', 'today-future', 'tomorrow', 'weekend']);
    assert.deepStrictEqual(filterTime('past'), ['previous-week', 'today-past']);
    assert.deepStrictEqual(filterTime('future'), ['today-future', 'tomorrow', 'weekend', 'next-week']);
  });

  it('uses available categories and searches titles plus any supplied description', () => {
    const items = [
      makePlan('Koşu Planı', { category: 'sport' }),
      makePlan('Desk session', { category: 'work', description: 'Project Aurora planning' }),
      makePlan('Reading', { category: 'study' }),
    ];
    assert.deepStrictEqual(getPlanCategories(items), ['sport', 'study', 'work']);
    assert.deepStrictEqual(ids(sortAndFilterPlans(items, { ...DEFAULT_PLAN_FILTERS, category: 'sport' }, 'created_newest', now)), ['Koşu Planı']);
    assert.deepStrictEqual(ids(sortAndFilterPlans(items, { ...DEFAULT_PLAN_FILTERS, search: 'aurora' }, 'created_newest', now)), ['Desk session']);
    assert.deepStrictEqual(ids(sortAndFilterPlans(items, { ...DEFAULT_PLAN_FILTERS, search: 'koşu' }, 'created_newest', now)), ['Koşu Planı']);
  });

  it('combines filters, counts active filters and returns an empty result for no matches', () => {
    const items = [
      makePlan('Planning Run', { category: 'sport', planned_start: atLocalTime(2026, 9, 26, 15) }),
      makePlan('Planning Study', { category: 'study', planned_start: atLocalTime(2026, 9, 26, 15) }),
      makePlan('Past Planning Run', { category: 'sport', planned_start: atLocalTime(2026, 9, 26, 10) }),
      makePlan('Done Planning Run', { category: 'sport', planned_start: atLocalTime(2026, 9, 26, 15), latest_outcome: { id: 'o4', plan_id: 'Done Planning Run', status: 'done', actual_start: null, postponed_to: null, note: null, reported_via: 'web', reported_at: atLocalTime(2026, 9, 26) } }),
    ];
    const combined: PlanFilters = { status: 'pending', time: 'future', category: 'sport', search: 'planning' };
    assert.deepStrictEqual(ids(sortAndFilterPlans(items, combined, 'created_newest', now)), ['Planning Run']);
    assert.strictEqual(countActivePlanFilters(combined), 4);
    assert.strictEqual(countActivePlanFilters(DEFAULT_PLAN_FILTERS), 0);
    assert.deepStrictEqual(sortAndFilterPlans(items, { ...combined, search: 'no such plan' }, 'created_newest', now), []);
  });
});

describe('Plan editing and deletion API', () => {
  const originalFetch = globalThis.fetch;
  const editable = {
    title: 'Updated Run',
    category: 'sport' as const,
    planned_start: '2026-10-18T18:30:00+03:00',
    planned_end: '2026-10-18T19:30:00+03:00',
  };

  it('validates supported plan fields and rejects invalid times', () => {
    assert.strictEqual(validatePlanForUpdate(editable), null);
    assert.match(validatePlanForUpdate({ ...editable, title: '  ' }) || '', /title/i);
    assert.match(validatePlanForUpdate({ ...editable, planned_end: editable.planned_start }) || '', /after/i);
  });

  it('updates the specified plan with the authenticated API client', async () => {
    let requestUrl = '';
    let requestMethod = '';
    let requestBody: Record<string, unknown> = {};
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      requestUrl = url;
      requestMethod = init?.method || '';
      requestBody = JSON.parse(String(init?.body || '{}'));
      return new Response(JSON.stringify({
        id: 'plan-1', ...editable, recurrence_rule: null, source: 'text',
        created_at: '2026-10-17T12:00:00+03:00', latest_outcome: null,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }) as typeof fetch;
    try {
      const plan = await updatePlan('plan-1', { ...editable, title: ' Updated Run ' });
      assert.ok(requestUrl.endsWith('/plans/plan-1'));
      assert.strictEqual(requestMethod, 'PUT');
      assert.strictEqual(requestBody.title, 'Updated Run');
      assert.strictEqual(plan.id, 'plan-1');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('sends DELETE for the selected plan and propagates backend errors', async () => {
    let requestUrl = '';
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      requestUrl = url;
      assert.strictEqual(init?.method, 'DELETE');
      return new Response(null, { status: 204 });
    }) as typeof fetch;
    try {
      await deletePlan('plan-2');
      assert.ok(requestUrl.endsWith('/plans/plan-2'));

      globalThis.fetch = (async () => new Response(
        JSON.stringify({ error: 'not_found', message: 'Plan not found.' }),
        { status: 404, headers: { 'Content-Type': 'application/json' } }
      )) as typeof fetch;
      await assert.rejects(() => deletePlan('plan-2'), { name: 'ApiError', status: 404 });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});

describe('GAP-AI W1-3: Plan Listing and Outcome Reporting Tests', () => {
  const originalFetch = globalThis.fetch;

  describe('1. Plan Listing (listPlans & GET /plans)', () => {
    it('1.1 successfully loads and lists plans from GET /plans', async () => {
      globalThis.fetch = (async (url: string) => {
        assert.ok(url.includes('/plans'));
        return new Response(
          JSON.stringify({
            items: [
              {
                id: 'plan-1',
                title: 'Sabah Koşusu',
                category: 'sport',
                planned_start: '2026-10-18T08:00:00+03:00',
                planned_end: '2026-10-18T09:00:00+03:00',
                recurrence_rule: null,
                source: 'text',
                created_at: '2026-10-17T12:00:00+03:00',
                latest_outcome: null,
              },
              {
                id: 'plan-2',
                title: 'Ekip Toplantısı',
                category: 'meeting',
                planned_start: '2026-10-18T10:00:00+03:00',
                planned_end: '2026-10-18T11:00:00+03:00',
                recurrence_rule: null,
                source: 'text',
                created_at: '2026-10-17T12:30:00+03:00',
                latest_outcome: {
                  id: 'outcome-1',
                  plan_id: 'plan-2',
                  status: 'done',
                  actual_start: '2026-10-18T10:05:00+03:00',
                  postponed_to: null,
                  note: null,
                  reported_via: 'web',
                  reported_at: '2026-10-18T11:00:00+03:00',
                },
              },
            ],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        const plans = await listPlans({ mockMode: false });
        assert.strictEqual(plans.length, 2);
        assert.strictEqual(plans[0].id, 'plan-1');
        assert.strictEqual(plans[0].title, 'Sabah Koşusu');
        assert.strictEqual(plans[0].latest_outcome, null);

        assert.strictEqual(plans[1].id, 'plan-2');
        assert.ok(plans[1].latest_outcome);
        assert.strictEqual(plans[1].latest_outcome?.status, 'done');
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('1.2 returns empty list when backend returns empty items array', async () => {
      globalThis.fetch = (async () => {
        return new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }) as typeof fetch;

      try {
        const plans = await listPlans({ mockMode: false });
        assert.strictEqual(Array.isArray(plans), true);
        assert.strictEqual(plans.length, 0);
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('1.3 passes query parameters (from, to) to GET /plans', async () => {
      let requestedUrl = '';
      globalThis.fetch = (async (url: string) => {
        requestedUrl = url;
        return new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }) as typeof fetch;

      try {
        await listPlans({
          from: '2026-10-18T00:00:00+03:00',
          to: '2026-10-18T23:59:59+03:00',
          mockMode: false,
        });

        assert.ok(requestedUrl.includes('from=2026-10-18T00%3A00%3A00%2B03%3A00'));
        assert.ok(requestedUrl.includes('to=2026-10-18T23%3A59%3A59%2B03%3A00'));
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('1.4 throws ApiError when listing request fails (no silent mock fallback)', async () => {
      globalThis.fetch = (async () => {
        return new Response(
          JSON.stringify({
            error: 'unauthorized',
            message: 'Token is missing or invalid.',
          }),
          { status: 401, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        await assert.rejects(
          async () => {
            await listPlans({ mockMode: false });
          },
          {
            name: 'ApiError',
            status: 401,
            errorType: 'unauthorized',
          }
        );
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('1.5 returns deterministic mock plans when mockMode is true', async () => {
      const plans = await listPlans({ mockMode: true });
      assert.ok(Array.isArray(plans));
      assert.ok(plans.length >= 3);
      assert.strictEqual(plans[0].title, 'Sabah Koşusu');
    });
  });

  describe('2. Outcome Reporting (reportPlanOutcome & POST /plans/{id}/outcome)', () => {
    it('2.1 reports "done" outcome with reported_via: "web" to correct URL', async () => {
      let capturedUrl = '';
      let capturedBody: Record<string, unknown> = {};

      globalThis.fetch = (async (url: string, init?: RequestInit) => {
        capturedUrl = url;
        capturedBody = JSON.parse((init?.body as string) || '{}');

        return new Response(
          JSON.stringify({
            id: 'outcome-101',
            plan_id: 'plan-123',
            status: 'done',
            actual_start: null,
            postponed_to: null,
            note: null,
            reported_via: 'web',
            reported_at: '2026-10-18T09:30:00+03:00',
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        const outcome = await reportPlanOutcome('plan-123', 'done', {
          mockMode: false,
        });

        assert.ok(capturedUrl.endsWith('/plans/plan-123/outcome'));
        assert.strictEqual(capturedBody.status, 'done');
        assert.strictEqual(capturedBody.reported_via, 'web');
        assert.strictEqual(outcome.id, 'outcome-101');
        assert.strictEqual(outcome.status, 'done');
        assert.strictEqual(outcome.reported_via, 'web');
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('2.2 reports "postponed" outcome with reported_via: "web"', async () => {
      let capturedBody: Record<string, unknown> = {};

      globalThis.fetch = (async (_url: string, init?: RequestInit) => {
        capturedBody = JSON.parse((init?.body as string) || '{}');

        return new Response(
          JSON.stringify({
            id: 'outcome-102',
            plan_id: 'plan-123',
            status: 'postponed',
            actual_start: null,
            postponed_to: '2026-10-19T10:00:00+03:00',
            note: 'Hava muhalefeti',
            reported_via: 'web',
            reported_at: '2026-10-18T09:30:00+03:00',
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        const outcome = await reportPlanOutcome('plan-123', 'postponed', {
          postponed_to: '2026-10-19T10:00:00+03:00',
          note: 'Hava muhalefeti',
          mockMode: false,
        });

        assert.strictEqual(capturedBody.status, 'postponed');
        assert.strictEqual(capturedBody.reported_via, 'web');
        assert.strictEqual(capturedBody.postponed_to, '2026-10-19T10:00:00+03:00');
        assert.strictEqual(capturedBody.note, 'Hava muhalefeti');
        assert.strictEqual(outcome.status, 'postponed');
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('2.3 reports "skipped" outcome with reported_via: "web"', async () => {
      let capturedBody: Record<string, unknown> = {};

      globalThis.fetch = (async (_url: string, init?: RequestInit) => {
        capturedBody = JSON.parse((init?.body as string) || '{}');

        return new Response(
          JSON.stringify({
            id: 'outcome-103',
            plan_id: 'plan-456',
            status: 'skipped',
            actual_start: null,
            postponed_to: null,
            note: null,
            reported_via: 'web',
            reported_at: '2026-10-18T09:30:00+03:00',
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        const outcome = await reportPlanOutcome('plan-456', 'skipped', {
          mockMode: false,
        });

        assert.strictEqual(capturedBody.status, 'skipped');
        assert.strictEqual(capturedBody.reported_via, 'web');
        assert.strictEqual(outcome.status, 'skipped');
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('2.4 rejects empty planId with validation error', async () => {
      await assert.rejects(
        async () => {
          await reportPlanOutcome('   ', 'done', { mockMode: false });
        },
        {
          name: 'ApiError',
          status: 422,
          errorType: 'validation_error',
        }
      );
    });

    it('2.5 rejects invalid status enum with validation error', async () => {
      await assert.rejects(
        async () => {
          // @ts-expect-error Testing invalid runtime enum value
          await reportPlanOutcome('plan-1', 'cancelled', { mockMode: false });
        },
        {
          name: 'ApiError',
          status: 422,
          errorType: 'validation_error',
        }
      );
    });

    it('2.6 propagates 404 not_found error on foreign or missing plan (K-1)', async () => {
      globalThis.fetch = (async () => {
        return new Response(
          JSON.stringify({
            error: 'not_found',
            message: 'Kaynak bu kullanıcı için bulunamadı.',
          }),
          { status: 404, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        await assert.rejects(
          async () => {
            await reportPlanOutcome('foreign-plan-id', 'done', {
              mockMode: false,
            });
          },
          {
            name: 'ApiError',
            status: 404,
            errorType: 'not_found',
            message: 'Kaynak bu kullanıcı için bulunamadı.',
          }
        );
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('2.7 propagates 401 unauthorized error on missing or invalid token', async () => {
      globalThis.fetch = (async () => {
        return new Response(
          JSON.stringify({
            error: 'unauthorized',
            message: 'Token is missing or invalid.',
          }),
          { status: 401, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        await assert.rejects(
          async () => {
            await reportPlanOutcome('plan-1', 'done', { mockMode: false });
          },
          {
            name: 'ApiError',
            status: 401,
            errorType: 'unauthorized',
          }
        );
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('2.8 handles malformed or non-JSON backend error safely', async () => {
      globalThis.fetch = (async () => {
        return new Response('502 Bad Gateway Server Error', {
          status: 502,
          statusText: 'Bad Gateway',
        });
      }) as typeof fetch;

      try {
        await assert.rejects(
          async () => {
            await reportPlanOutcome('plan-1', 'done', { mockMode: false });
          },
          {
            name: 'ApiError',
            status: 502,
          }
        );
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('2.9 returns valid PlanOutcome in mockMode', async () => {
      const outcome = await reportPlanOutcome('plan-test-mock', 'done', {
        mockMode: true,
      });

      assert.strictEqual(outcome.plan_id, 'plan-test-mock');
      assert.strictEqual(outcome.status, 'done');
      assert.strictEqual(outcome.reported_via, 'web');
      assert.ok(isValidUUID(outcome.id));
    });
  });

  describe('3. Plan State Update and User Isolation Logic', () => {
    it('3.1 updating outcome for Plan A does not mutate or affect Plan B', () => {
      const initialPlans: Plan[] = [
        {
          id: 'plan-A',
          title: 'Plan A',
          category: 'sport',
          planned_start: '2026-10-18T10:00:00+03:00',
          planned_end: '2026-10-18T11:00:00+03:00',
          recurrence_rule: null,
          source: 'text',
          created_at: '2026-10-17T10:00:00+03:00',
          latest_outcome: null,
        },
        {
          id: 'plan-B',
          title: 'Plan B',
          category: 'study',
          planned_start: '2026-10-18T14:00:00+03:00',
          planned_end: '2026-10-18T16:00:00+03:00',
          recurrence_rule: null,
          source: 'text',
          created_at: '2026-10-17T11:00:00+03:00',
          latest_outcome: null,
        },
      ];

      const newOutcome: PlanOutcome = {
        id: 'outcome-A',
        plan_id: 'plan-A',
        status: 'done',
        actual_start: null,
        postponed_to: null,
        note: null,
        reported_via: 'web',
        reported_at: '2026-10-18T11:00:00+03:00',
      };

      // State updater logic as implemented in PlanList:
      const updatedPlans = initialPlans.map((p) =>
        p.id === 'plan-A' ? { ...p, latest_outcome: newOutcome } : p
      );

      assert.strictEqual(updatedPlans[0].id, 'plan-A');
      assert.strictEqual(updatedPlans[0].latest_outcome?.status, 'done');

      assert.strictEqual(updatedPlans[1].id, 'plan-B');
      assert.strictEqual(updatedPlans[1].latest_outcome, null);
    });

    it('3.2 mockListPlans produces plans matching Plan interface with latest_outcome structure', () => {
      const mockItems = mockListPlans();
      for (const plan of mockItems) {
        assert.ok(plan.id);
        assert.ok(plan.title);
        assert.ok(plan.planned_start);
        assert.ok(plan.planned_end);
        assert.ok(['text', 'voice', 'device'].includes(plan.source));
        if (plan.latest_outcome) {
          assert.strictEqual(plan.latest_outcome.plan_id, plan.id);
          assert.ok(
            ['done', 'postponed', 'skipped'].includes(
              plan.latest_outcome.status
            )
          );
          assert.strictEqual(plan.latest_outcome.reported_via, 'web');
        }
      }
    });

    it('3.3 mockReportPlanOutcome produces strictly conforming outcome event', () => {
      const outcome = mockReportPlanOutcome('test-uuid', 'postponed', {
        postponed_to: '2026-10-20T10:00:00+03:00',
        note: 'Postponed due to meeting conflict',
      });

      assert.strictEqual(outcome.plan_id, 'test-uuid');
      assert.strictEqual(outcome.status, 'postponed');
      assert.strictEqual(outcome.reported_via, 'web');
      assert.strictEqual(
        outcome.postponed_to,
        '2026-10-20T10:00:00+03:00'
      );
      assert.strictEqual(
        outcome.note,
        'Postponed due to meeting conflict'
      );
      assert.ok(isValidUUID(outcome.id));
    });
  });

  describe('4. Pydantic Error Normalization and Outcome Contract Invariants', () => {
    const originalFetch = globalThis.fetch;

    it('4.1 normalizes Pydantic array-format detail errors into clean string without React crash', async () => {
      globalThis.fetch = (async () => {
        return new Response(
          JSON.stringify({
            detail: [
              { loc: ['body', 'parsed_plan', 'title'], msg: 'Field required', type: 'missing' },
              { loc: ['body', 'parsed_plan', 'date'], msg: 'Invalid date format', type: 'value_error' },
            ],
          }),
          { status: 422, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        await assert.rejects(
          async () => {
            await apiFetch('/plans', { method: 'POST', body: '{}' });
          },
          (err: unknown) => {
            assert.ok(err instanceof ApiError);
            assert.strictEqual(typeof err.message, 'string');
            assert.ok(err.message.includes('parsed_plan.title: Field required'));
            assert.ok(err.message.includes('parsed_plan.date: Invalid date format'));
            return true;
          }
        );
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('4.2 forces postponed_to to null when reporting "done" status even if provided', async () => {
      let capturedBody: Record<string, unknown> = {};

      globalThis.fetch = (async (_url: string, init?: RequestInit) => {
        capturedBody = JSON.parse((init?.body as string) || '{}');
        return new Response(
          JSON.stringify({
            id: 'outcome-uuid-1',
            plan_id: 'plan-uuid-1',
            status: 'done',
            actual_start: null,
            postponed_to: null,
            note: null,
            reported_via: 'web',
            reported_at: '2026-10-24T12:00:00+03:00',
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        await reportPlanOutcome('plan-uuid-1', 'done', {
          postponed_to: '2026-10-25T10:00:00+03:00',
        });

        assert.strictEqual(capturedBody.status, 'done');
        assert.strictEqual(capturedBody.reported_via, 'web');
        assert.strictEqual(capturedBody.postponed_to, null);
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('4.3 forces postponed_to to null when reporting "skipped" status even if provided', async () => {
      let capturedBody: Record<string, unknown> = {};

      globalThis.fetch = (async (_url: string, init?: RequestInit) => {
        capturedBody = JSON.parse((init?.body as string) || '{}');
        return new Response(
          JSON.stringify({
            id: 'outcome-uuid-2',
            plan_id: 'plan-uuid-2',
            status: 'skipped',
            actual_start: null,
            postponed_to: null,
            note: null,
            reported_via: 'web',
            reported_at: '2026-10-24T12:00:00+03:00',
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        await reportPlanOutcome('plan-uuid-2', 'skipped', {
          postponed_to: '2026-10-25T10:00:00+03:00',
        });

        assert.strictEqual(capturedBody.status, 'skipped');
        assert.strictEqual(capturedBody.reported_via, 'web');
        assert.strictEqual(capturedBody.postponed_to, null);
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('4.4 preserves postponed_to when reporting "postponed" status', async () => {
      let capturedBody: Record<string, unknown> = {};

      globalThis.fetch = (async (_url: string, init?: RequestInit) => {
        capturedBody = JSON.parse((init?.body as string) || '{}');
        return new Response(
          JSON.stringify({
            id: 'outcome-uuid-3',
            plan_id: 'plan-uuid-3',
            status: 'postponed',
            actual_start: null,
            postponed_to: '2026-10-25T10:00:00+03:00',
            note: null,
            reported_via: 'web',
            reported_at: '2026-10-24T12:00:00+03:00',
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        await reportPlanOutcome('plan-uuid-3', 'postponed', {
          postponed_to: '2026-10-25T10:00:00+03:00',
        });

        assert.strictEqual(capturedBody.status, 'postponed');
        assert.strictEqual(capturedBody.reported_via, 'web');
        assert.strictEqual(capturedBody.postponed_to, '2026-10-25T10:00:00+03:00');
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('4.5 normalizes Pydantic object-format detail errors into JSON string', async () => {
      globalThis.fetch = (async () => {
        return new Response(
          JSON.stringify({
            detail: { error_code: 'RATE_LIMIT', retry_after: 30 },
          }),
          { status: 429, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      try {
        await assert.rejects(
          async () => {
            await apiFetch('/plans', { method: 'GET' });
          },
          (err: unknown) => {
            assert.ok(err instanceof ApiError);
            assert.strictEqual(typeof err.message, 'string');
            assert.ok(err.message.includes('RATE_LIMIT'));
            return true;
          }
        );
      } finally {
        globalThis.fetch = originalFetch;
      }
    });
  });

  describe('5. Form Validation & UI State Integrity Tests', () => {
    const validPlan: ParsedPlan = {
      intent: 'create_plan',
      title: 'Kitap Okuma',
      category: 'personal',
      date: '2026-10-25',
      time: '19:30',
      duration_minutes: 45,
      recurrence: null,
      language: 'tr',
      needs_weather_check: false,
      clarification_question: null,
      confidence: 0.95,
    };

    it('5.1 validatePlanForCreation accepts fully valid plan', () => {
      assert.strictEqual(validatePlanForCreation(validPlan), null);
    });

    it('5.2 validatePlanForCreation rejects non-create_plan intent', () => {
      const clarifyPlan: ParsedPlan = { ...validPlan, intent: 'clarify' };
      assert.strictEqual(
        validatePlanForCreation(clarifyPlan),
        'Only create_plan intents can be saved.'
      );
    });

    it('5.3 validatePlanForCreation rejects empty or whitespace-only title', () => {
      assert.strictEqual(
        validatePlanForCreation({ ...validPlan, title: '' }),
        'Plan title cannot be empty.'
      );
      assert.strictEqual(
        validatePlanForCreation({ ...validPlan, title: '   ' }),
        'Plan title cannot be empty.'
      );
      assert.strictEqual(
        validatePlanForCreation({ ...validPlan, title: null }),
        'Plan title cannot be empty.'
      );
    });

    it('5.4 validatePlanForCreation rejects invalid date format', () => {
      const invalidDates = ['', '2026-1-1', '26-10-2026', '2026/10/25', 'invalid'];
      for (const d of invalidDates) {
        assert.strictEqual(
          validatePlanForCreation({ ...validPlan, date: d }),
          'A valid plan date (YYYY-MM-DD) is required.'
        );
      }
    });

    it('5.5 validatePlanForCreation rejects invalid time format', () => {
      const invalidTimes = ['', '9:00', '25:00', '18:60', '18:0', 'invalid'];
      for (const t of invalidTimes) {
        assert.strictEqual(
          validatePlanForCreation({ ...validPlan, time: t }),
          'A valid plan time (HH:MM in 24-hour format) is required.'
        );
      }
    });

    it('5.6 validatePlanForCreation rejects duration outside 5-1440 minutes', () => {
      assert.strictEqual(
        validatePlanForCreation({ ...validPlan, duration_minutes: 4 }),
        'Duration must be between 5 and 1440 minutes, or left empty for default 60 minutes.'
      );
      assert.strictEqual(
        validatePlanForCreation({ ...validPlan, duration_minutes: 1441 }),
        'Duration must be between 5 and 1440 minutes, or left empty for default 60 minutes.'
      );
    });

    it('5.7 validatePlanForCreation accepts duration_minutes null or undefined', () => {
      assert.strictEqual(
        validatePlanForCreation({ ...validPlan, duration_minutes: null }),
        null
      );
      assert.strictEqual(
        validatePlanForCreation({ ...validPlan, duration_minutes: undefined as unknown as null }),
        null
      );
    });

    it('5.8 formatOutcomeTime safely formats timestamps without throwing or returning Invalid Date', () => {
      assert.strictEqual(formatOutcomeTime(null), '');
      assert.strictEqual(formatOutcomeTime(undefined), '');
      assert.strictEqual(formatOutcomeTime('not-a-valid-date'), '');

      const validResult = formatOutcomeTime('2026-10-24T18:30:00+03:00');
      assert.ok(validResult.length > 0);
      assert.strictEqual(validResult.includes('Invalid Date'), false);
    });
  });
});
