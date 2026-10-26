import { apiFetch, ApiError } from './client.ts';
import type {
  OutcomeReportRequest,
  OutcomeStatus,
  ParsedPlan,
  ParseRequest,
  Plan,
  PlanCreateRequest,
  PlanListResponse,
  PlanOutcome,
  PlanUpdateRequest,
} from '../types/plan.ts';
import { generateIdempotencyKey, isValidUUID } from '../utils/idempotency.ts';


/**
 * Returns today's calendar date in local timezone formatted as YYYY-MM-DD.
 */
export function getLocalCurrentDate(baseDate: Date = new Date()): string {
  const year = baseDate.getFullYear();
  const month = String(baseDate.getMonth() + 1).padStart(2, '0');
  const day = String(baseDate.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Safely formats an ISO timestamp to local time for outcome badges.
 * Never throws or produces "Invalid Date".
 */
export function formatOutcomeTime(reportedAt: string | null | undefined): string {
  if (!reportedAt) return '';
  const d = new Date(reportedAt);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

export interface ParsePlanOptions {
  language?: 'tr' | 'en';
  mockMode?: boolean;
}

export interface SavePlanOptions {
  mockMode?: boolean;
}

export interface PlanSuggestion {
  plan_id: string;
  reason: 'weather' | 'pattern';
  message: string;
  proposed_start: string;
  proposed_end: string;
  evidence: { forecast?: string | null; adherence_pct?: number | null; outcome_count?: number | null };
}

const pendingSuggestions = new Map<string, Promise<PlanSuggestion | null>>();

export function fetchPlanSuggestion(planId: string): Promise<PlanSuggestion | null> {
  const existing = pendingSuggestions.get(planId);
  if (existing) return existing;
  const request = fetchPlanSuggestionOnce(planId);
  pendingSuggestions.set(planId, request);
  void request.finally(() => {
    if (pendingSuggestions.get(planId) === request) pendingSuggestions.delete(planId);
  }).catch(() => undefined);
  return request;
}

async function fetchPlanSuggestionOnce(planId: string): Promise<PlanSuggestion | null> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  try {
    const result = await apiFetch<{ suggestion: PlanSuggestion | null }>(
      `/plans/${encodeURIComponent(planId)}/suggestion`, { method: 'GET', signal: controller.signal }
    );
    return result.suggestion ?? null;
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * Deterministic mock implementation for B2-2 independent testing and offline development.
 * Never used silently in production flow.
 */
/**
 * Normalizes text by lowercasing and folding Turkish characters for robust matching.
 */
function foldTurkishText(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[ıİiî]/g, 'i')
    .replace(/[ğg]/g, 'g')
    .replace(/[üuû]/g, 'u')
    .replace(/[şs]/g, 's')
    .replace(/[öoô]/g, 'o')
    .replace(/[çc]/g, 'c');
}

const CHIT_CHAT_KEYWORDS = [
  'fikra',
  'saka',
  'espri',
  'komik',
  'merhaba',
  'selam',
  'gunaydin',
  'iyi gunler',
  'iyi aksamlar',
  'iyi geceler',
  'nasilsin',
  'naber',
  'ne haber',
  'kimsin',
  'adin ne',
  'ne yapabilirsin',
  'yardim et',
  'sohbet',
  'sarki',
  'muhabbet',
  'hava durumu',
  'hava nasil',
  'joke',
  'hello',
  'how are you',
];

const SPORT_KEYWORDS = [
  'kosu',
  'kos',
  'yuruyus',
  'spor',
  'fitness',
  'gym',
  'antrenman',
  'yuzme',
  'bisiklet',
  'futbol',
  'basketbol',
  'tenis',
  'pilates',
  'yoga',
  'run',
  'workout',
];

const STUDY_KEYWORDS = [
  'ders',
  'calis',
  'kod',
  'kodlama',
  'odev',
  'sinav',
  'okuma',
  'kitap',
  'study',
  'code',
];

const MEETING_KEYWORDS = [
  'toplanti',
  'gorusme',
  'mulakat',
  'sunum',
  'proje',
  'rapor',
  'meeting',
  'interview',
  'is',
];

const HEALTH_KEYWORDS = [
  'doktor',
  'hastane',
  'disci',
  'randevu',
  'ilac',
  'saglik',
  'doctor',
  'dentist',
];

const SOCIAL_KEYWORDS = [
  'bulusma',
  'yemek',
  'kahvalti',
  'aksam yemegi',
  'sinema',
  'konser',
  'tiyatro',
  'kahve',
  'lunch',
  'dinner',
];

const ALL_ACTIVITIES = [
  ...SPORT_KEYWORDS,
  ...STUDY_KEYWORDS,
  ...MEETING_KEYWORDS,
  ...HEALTH_KEYWORDS,
  ...SOCIAL_KEYWORDS,
  'yapacagim',
  'edecegim',
  'gidecegim',
  'katilacagim',
  'plan',
  'planla',
];

/**
 * Deterministic mock implementation for B2-2 independent testing and offline development.
 * Never used silently in production flow.
 */
export function mockParsePlan(text: string, options?: ParsePlanOptions): ParsedPlan {
  const lower = text.toLowerCase().trim();
  const folded = foldTurkishText(text);
  const currentDate = getLocalCurrentDate();
  const useEnglish = options?.language === 'en';

  const isChitChat = CHIT_CHAT_KEYWORDS.some((k) => folded.includes(k));
  const hasActivity = ALL_ACTIVITIES.some((k) => folded.includes(k));

  // If input is chit-chat without an explicit activity, or has no activity at all:
  // It is strictly unsupported according to D-004 and ai/schema.json.
  if ((isChitChat && !hasActivity) || !hasActivity) {
    return {
      intent: 'unsupported',
      title: null,
      category: null,
      date: null,
      time: null,
      duration_minutes: null,
      recurrence: null,
      language: options?.language || 'tr',
      needs_weather_check: false,
      clarification_question: null,
      confidence: 0.98,
    };
  }

  // Determine activity title and category
  let category: ParsedPlan['category'] = 'other';
  let title = useEnglish ? 'Planned Activity' : 'Planlanan Aktivite';
  let needsWeather = false;

  if (SPORT_KEYWORDS.some((k) => folded.includes(k))) {
    category = 'sport';
    title = useEnglish ? 'Run' : 'Koşu';
    needsWeather = true;
  } else if (STUDY_KEYWORDS.some((k) => folded.includes(k))) {
    category = 'study';
    title = useEnglish ? 'Study Session' : 'Ders Çalışma';
  } else if (MEETING_KEYWORDS.some((k) => folded.includes(k))) {
    category = 'meeting';
    title = useEnglish ? 'Meeting' : 'Toplantı';
  } else if (HEALTH_KEYWORDS.some((k) => folded.includes(k))) {
    category = 'health';
    title = useEnglish ? 'Health Appointment' : 'Sağlık Randevusu';
  } else if (SOCIAL_KEYWORDS.some((k) => folded.includes(k))) {
    category = 'social';
    title = useEnglish ? 'Social Event' : 'Sosyal Buluşma';
  }

  // Check if time is specified:
  // - 18:00, 18.00
  // - saat 18, saat 9
  // - 18'de, 18 de, 18'te, 18 te
  // - ogleden sonra, aksam, sabah, gece
  const hasTimePattern =
    /\b([01]?\d|2[0-3])[:.][0-5]\d\b/.test(lower) ||
    /\bsaat\s*([01]?\d|2[0-3])\b/.test(lower) ||
    /\b([01]?\d|2[0-3])\s*(?:'?[dts][ea])\b/.test(lower) ||
    /\b(ogleden sonra|aksam|sabah|gece)\b/.test(folded);

  if (!hasTimePattern) {
    const question = useEnglish
      ? category === 'sport'
        ? 'What time would you like to go for your run?'
        : category === 'study'
          ? 'What time would you like to start studying?'
          : `What time would you like to start your ${title.toLowerCase()}?`
      : category === 'sport'
        ? 'Koşuya saat kaçta çıkmak istersiniz?'
        : category === 'study'
          ? 'Çalışmaya saat kaçta başlamak istersiniz?'
          : `${title} aktivitesine saat kaçta başlamak istersiniz?`;

    return {
      intent: 'clarify',
      title,
      category,
      date: currentDate,
      time: null,
      duration_minutes: null,
      recurrence: null,
      language: options?.language || 'tr',
      needs_weather_check: needsWeather,
      clarification_question: question,
      confidence: 0.85,
    };
  }

  // Extract time if present, default to "18:00"
  let parsedTime = '18:00';
  const hhMmMatch = lower.match(/\b([01]?\d|2[0-3])[:.]([0-5]\d)\b/);
  if (hhMmMatch) {
    const hh = String(Number(hhMmMatch[1])).padStart(2, '0');
    const mm = hhMmMatch[2];
    parsedTime = `${hh}:${mm}`;
  } else {
    const deMatch = lower.match(/\b([01]?\d|2[0-3])\s*(?:'?[dts][ea])\b/);
    if (deMatch) {
      const hh = String(Number(deMatch[1])).padStart(2, '0');
      parsedTime = `${hh}:00`;
    } else {
      const saatMatch = lower.match(/\bsaat\s*([01]?\d|2[0-3])\b/);
      if (saatMatch) {
        const hh = String(Number(saatMatch[1])).padStart(2, '0');
        parsedTime = `${hh}:00`;
      }
    }
  }

  return {
    intent: 'create_plan',
    title,
    category,
    date: currentDate,
    time: parsedTime,
    duration_minutes: 60,
    recurrence: null,
    language: options?.language || 'tr',
    needs_weather_check: needsWeather,
    clarification_question: null,
    confidence: 0.95,
  };
}

/**
 * Deterministic mock save implementation.
 */
export function mockSavePlan(
  parsedPlan: ParsedPlan,
  _idempotencyKey: string
): Plan {
  const planDate = parsedPlan.date || getLocalCurrentDate();
  const planTime = parsedPlan.time || '18:00';
  const duration = parsedPlan.duration_minutes ?? 60;

  const startIso = `${planDate}T${planTime}:00+03:00`;
  const startDate = new Date(startIso);
  const endDate = new Date(startDate.getTime() + duration * 60 * 1000);
  const endIso = endDate.toISOString();

  return {
    id: generateIdempotencyKey(),
    title: parsedPlan.title || 'Yeni Plan',
    category: parsedPlan.category || 'other',
    planned_start: startIso,
    planned_end: endIso,
    recurrence_rule: parsedPlan.recurrence,
    source: 'text',
    created_at: new Date().toISOString(),
    latest_outcome: null,
  };
}

/**
 * Sends a natural language plan text to POST /parse.
 *
 * @throws {ApiError} when the backend rejects the request or fails.
 */
export async function parseNaturalLanguagePlan(
  text: string,
  options?: ParsePlanOptions
): Promise<ParsedPlan> {
  const trimmed = text.trim();
  if (!trimmed) {
    throw new ApiError('Plan text cannot be empty.', 422, 'validation_error');
  }

  if (options?.mockMode) {
    // Controlled mock mode (simulated delay for realism):
    await new Promise((r) => setTimeout(r, 300));
    return mockParsePlan(trimmed, options);
  }

  const currentDate = getLocalCurrentDate();
  const payload: ParseRequest = {
    text: trimmed,
    current_date: currentDate,
    ...(options?.language ? { language: options.language } : {}),
  };

  return apiFetch<ParsedPlan>('/parse', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Validates a confirmed plan before submitting to POST /plans.
 * Returns null if valid, or a descriptive error string if invalid.
 */
export function validatePlanForCreation(parsedPlan: ParsedPlan): string | null {
  if (parsedPlan.intent !== 'create_plan') {
    return 'Only create_plan intents can be saved.';
  }

  const trimmedTitle = parsedPlan.title?.trim() || '';
  if (!trimmedTitle) {
    return 'Plan title cannot be empty.';
  }

  const trimmedDate = parsedPlan.date?.trim() || '';
  if (!trimmedDate || !/^\d{4}-\d{2}-\d{2}$/.test(trimmedDate)) {
    return 'A valid plan date (YYYY-MM-DD) is required.';
  }

  const trimmedTime = parsedPlan.time?.trim() || '';
  if (!trimmedTime || !/^([01]\d|2[0-3]):[0-5]\d$/.test(trimmedTime)) {
    return 'A valid plan time (HH:MM in 24-hour format) is required.';
  }

  if (
    parsedPlan.duration_minutes !== null &&
    parsedPlan.duration_minutes !== undefined &&
    (parsedPlan.duration_minutes < 5 ||
      parsedPlan.duration_minutes > 1440 ||
      Number.isNaN(parsedPlan.duration_minutes))
  ) {
    return 'Duration must be between 5 and 1440 minutes, or left empty for default 60 minutes.';
  }

  return null;
}

/**
 * Saves a confirmed plan via POST /plans with an Idempotency-Key header.
 *
 * @throws {ApiError} when validation fails or backend rejects the request.
 */
export async function createPlan(
  parsedPlan: ParsedPlan,
  idempotencyKey: string,
  options?: SavePlanOptions
): Promise<Plan> {
  const validationError = validatePlanForCreation(parsedPlan);
  if (validationError) {
    throw new ApiError(validationError, 422, 'validation_error');
  }

  if (!isValidUUID(idempotencyKey)) {
    throw new ApiError(
      'Invalid idempotency key format. A UUID v4 is required.',
      422,
      'validation_error'
    );
  }

  if (options?.mockMode) {
    await new Promise((r) => setTimeout(r, 400));
    return mockSavePlan(parsedPlan, idempotencyKey);
  }

  const payload: PlanCreateRequest = {
    parsed_plan: parsedPlan,
    source: 'text',
  };

  return apiFetch<Plan>('/plans', {
    method: 'POST',
    headers: {
      'Idempotency-Key': idempotencyKey,
    },
    body: JSON.stringify(payload),
  });
}

export interface ListPlansOptions {
  from?: string;
  to?: string;
  mockMode?: boolean;
}

export interface ReportOutcomeOptions {
  actual_start?: string | null;
  postponed_to?: string | null;
  note?: string | null;
  mockMode?: boolean;
}

/**
 * Deterministic mock plan list for offline testing and demo flows.
 * Never used silently in live API requests.
 */
export function mockListPlans(): Plan[] {
  const today = getLocalCurrentDate();
  return [
    {
      id: '550e8400-e29b-41d4-a716-446655440001',
      title: 'Sabah Koşusu',
      category: 'sport',
      planned_start: `${today}T08:00:00+03:00`,
      planned_end: `${today}T09:00:00+03:00`,
      recurrence_rule: null,
      source: 'text',
      created_at: `${today}T07:00:00+03:00`,
      latest_outcome: null,
    },
    {
      id: '550e8400-e29b-41d4-a716-446655440002',
      title: 'Haftalık Ekip Senkronizasyonu',
      category: 'meeting',
      planned_start: `${today}T11:00:00+03:00`,
      planned_end: `${today}T12:00:00+03:00`,
      recurrence_rule: 'FREQ=WEEKLY',
      source: 'text',
      created_at: `${today}T07:15:00+03:00`,
      latest_outcome: {
        id: '6ba7b810-9dad-11d1-80b4-00c04fd43001',
        plan_id: '550e8400-e29b-41d4-a716-446655440002',
        status: 'done',
        actual_start: `${today}T11:05:00+03:00`,
        postponed_to: null,
        note: null,
        reported_via: 'web',
        reported_at: `${today}T12:05:00+03:00`,
      },
    },
    {
      id: '550e8400-e29b-41d4-a716-446655440003',
      title: 'GAP-AI Frontend Geliştirme',
      category: 'study',
      planned_start: `${today}T14:30:00+03:00`,
      planned_end: `${today}T16:30:00+03:00`,
      recurrence_rule: null,
      source: 'text',
      created_at: `${today}T07:30:00+03:00`,
      latest_outcome: null,
    },
    {
      id: '550e8400-e29b-41d4-a716-446655440004',
      title: 'Akşam Yürüyüşü',
      category: 'sport',
      planned_start: `${today}T19:00:00+03:00`,
      planned_end: `${today}T20:00:00+03:00`,
      recurrence_rule: null,
      source: 'text',
      created_at: `${today}T07:45:00+03:00`,
      latest_outcome: null,
    },
  ];
}

/**
 * Deterministic mock outcome creation.
 */
export function mockReportPlanOutcome(
  planId: string,
  status: OutcomeStatus,
  options?: ReportOutcomeOptions
): PlanOutcome {
  return {
    id: generateIdempotencyKey(),
    plan_id: planId,
    status,
    actual_start: options?.actual_start ?? null,
    postponed_to: options?.postponed_to ?? null,
    note: options?.note ?? null,
    reported_via: 'web',
    reported_at: new Date().toISOString(),
  };
}

/**
 * Fetches the authenticated user's plans via GET /plans.
 *
 * @throws {ApiError} when the backend rejects the request or network fails.
 */
export async function listPlans(options?: ListPlansOptions): Promise<Plan[]> {
  if (options?.mockMode) {
    await new Promise((r) => setTimeout(r, 200));
    return mockListPlans();
  }

  const queryParams = new URLSearchParams();
  if (options?.from) queryParams.set('from', options.from);
  if (options?.to) queryParams.set('to', options.to);
  const queryStr = queryParams.toString() ? `?${queryParams.toString()}` : '';

  const response = await apiFetch<PlanListResponse>(`/plans${queryStr}`, {
    method: 'GET',
  });

  return Array.isArray(response?.items) ? response.items : [];
}

const EDITABLE_PLAN_CATEGORIES = [
  'sport',
  'study',
  'work',
  'meeting',
  'health',
  'social',
  'personal',
  'other',
] as const;

/** Validates the complete editable plan payload before sending it to the API. */
export function validatePlanForUpdate(plan: PlanUpdateRequest): string | null {
  if (!plan.title.trim()) return 'Plan title cannot be empty.';
  if (!EDITABLE_PLAN_CATEGORIES.includes(plan.category)) {
    return 'Choose a valid plan category.';
  }
  for (const [field, value] of [
    ['start', plan.planned_start],
    ['end', plan.planned_end],
  ] as const) {
    if (!Number.isFinite(Date.parse(value)) || !/(Z|[+-]\d{2}:\d{2})$/i.test(value)) {
      return `Enter a valid ${field} date and time.`;
    }
  }
  if (Date.parse(plan.planned_end) <= Date.parse(plan.planned_start)) {
    return 'End date and time must be after the start.';
  }
  return null;
}

/** Persist supported editable fields through the authenticated API. */
export async function updatePlan(
  planId: string,
  changes: PlanUpdateRequest
): Promise<Plan> {
  const trimmedId = planId?.trim();
  if (!trimmedId) throw new ApiError('Plan ID cannot be empty.', 422, 'validation_error');

  const validationError = validatePlanForUpdate(changes);
  if (validationError) throw new ApiError(validationError, 422, 'validation_error');

  return apiFetch<Plan>(`/plans/${encodeURIComponent(trimmedId)}`, {
    method: 'PUT',
    body: JSON.stringify({
      ...changes,
      title: changes.title.trim(),
    }),
  });
}

/** Permanently deletes an owned plan. The backend applies the database FK rules. */
export async function deletePlan(planId: string): Promise<void> {
  const trimmedId = planId?.trim();
  if (!trimmedId) throw new ApiError('Plan ID cannot be empty.', 422, 'validation_error');

  await apiFetch<void>(`/plans/${encodeURIComponent(trimmedId)}`, {
    method: 'DELETE',
  });
}

/**
 * Reports an outcome for a plan via POST /plans/{id}/outcome.
 * Strictly uses `reported_via: "web"` according to docs/api-contract.md:243-258.
 *
 * @throws {ApiError} when validation fails or backend rejects the request.
 */
export async function reportPlanOutcome(
  planId: string,
  status: OutcomeStatus,
  options?: ReportOutcomeOptions
): Promise<PlanOutcome> {
  const trimmedId = planId?.trim();
  if (!trimmedId) {
    throw new ApiError('Plan ID cannot be empty.', 422, 'validation_error');
  }

  const validStatuses: OutcomeStatus[] = ['done', 'postponed', 'skipped'];
  if (!validStatuses.includes(status)) {
    throw new ApiError(
      `Invalid outcome status: ${status}. Expected done, postponed, or skipped.`,
      422,
      'validation_error'
    );
  }

  if (options?.mockMode) {
    await new Promise((r) => setTimeout(r, 300));
    return mockReportPlanOutcome(trimmedId, status, options);
  }

  const payload: OutcomeReportRequest = {
    status,
    reported_via: 'web',
    ...(options?.actual_start !== undefined ? { actual_start: options.actual_start } : { actual_start: null }),
    postponed_to: status === 'postponed' && options?.postponed_to !== undefined ? options.postponed_to : null,
    ...(options?.note !== undefined ? { note: options.note } : { note: null }),
  };

  return apiFetch<PlanOutcome>(`/plans/${encodeURIComponent(trimmedId)}/outcome`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
