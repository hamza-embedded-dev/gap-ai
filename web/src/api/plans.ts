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
  ConversationRequest,
  ConversationResponse,
  ConversationState,
  PendingPlan,
  ProposalSnapshot,
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

/**
 * Interactive Conversation API for multi-turn plan scheduling.
 * Shared backend conversation logic serving both Web and ESP32 clients.
 */

interface MockConversationSession {
  conversation_id: string;
  state: ConversationState;
  pending_plan: PendingPlan | null;
  created_plan: Plan | null;
  needs_confirmation: boolean;
  reply_text: string;
  clarification_question: string | null;
  confirmation_summary: string | null;
  proposal: ProposalSnapshot | null;
  awaiting_ampm_for_hour: number | null;
  confirmed_once: boolean;
}

const mockConversationSessions = new Map<string, MockConversationSession>();
let lastActiveMockConversationId: string | null = null;

function formatTime12h(timeStr: string): string {
  const parts = timeStr.split(':');
  const h = parseInt(parts[0], 10);
  const m = parts[1] || '00';
  const period = h >= 12 ? 'PM' : 'AM';
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${m} ${period}`;
}

function formatDurationEn(mins: number): string {
  if (mins === 60) return 'one hour';
  if (mins === 120) return 'two hours';
  if (mins === 180) return 'three hours';
  return `${mins} minutes`;
}

function formatDatePhraseEn(dateStr: string): string {
  const today = getLocalCurrentDate();
  const d = new Date(`${dateStr}T12:00:00Z`);
  const dayName = d.toLocaleDateString('en-US', { weekday: 'long', timeZone: 'UTC' });
  const monthName = d.toLocaleDateString('en-US', { month: 'long', timeZone: 'UTC' });
  const dayNum = d.getUTCDate();

  const todayDate = new Date(`${today}T12:00:00Z`);
  const diffDays = Math.round((d.getTime() - todayDate.getTime()) / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return 'today';
  if (diffDays === 1) return `tomorrow, ${dayName}, ${monthName} ${dayNum}`;
  return `${dayName}, ${monthName} ${dayNum}`;
}

function buildConfirmationSummary(pending: PendingPlan): string {
  const task = pending.title || 'activity';
  const datePhrase = pending.date ? formatDatePhraseEn(pending.date) : 'today';
  const timePhrase = pending.time ? formatTime12h(pending.time) : 'at 6:00 PM';
  const durationPhrase = formatDurationEn(pending.duration_minutes ?? 60);

  return `Create a plan to ${task.toLowerCase()} ${datePhrase} at ${timePhrase} for ${durationPhrase}?`;
}

export function mockSendConversationMessage(
  message: string,
  conversationId?: string | null,
  _options?: { language?: 'en' | 'tr' }
): ConversationResponse {
  const lower = message.toLowerCase().trim();
  const convId = conversationId || lastActiveMockConversationId || generateIdempotencyKey();
  let session = mockConversationSessions.get(convId);

  if (!session) {
    session = {
      conversation_id: convId,
      state: 'collecting_details',
      pending_plan: null,
      created_plan: null,
      needs_confirmation: false,
      reply_text: '',
      clarification_question: null,
      confirmation_summary: null,
      proposal: null,
      awaiting_ampm_for_hour: null,
      confirmed_once: false,
    };
    mockConversationSessions.set(convId, session);
    lastActiveMockConversationId = convId;
  }

  // 1. Check for cancellation
  if (
    /^(cancel|cancel that|stop|never mind|abort|no|dont save|don't save)$/i.test(lower) ||
    lower.includes('cancel that')
  ) {
    session.state = 'cancelled';
    session.pending_plan = null;
    session.needs_confirmation = false;
    session.clarification_question = null;
    session.confirmation_summary = null;
    session.reply_text = 'Plan creation has been cancelled. No plan was saved.';
    return {
      conversation_id: session.conversation_id,
      state: session.state,
      reply_text: session.reply_text,
      clarification_question: null,
      confirmation_summary: null,
      pending_plan: null,
      created_plan: null,
      needs_confirmation: false,
      proposal: null,
    };
  }

  // 2. Check for explicit confirmation when awaiting confirmation
  if (
    session.state === 'awaiting_confirmation' &&
    (/^(yes|confirm|sure|sounds good|yes please|create it|save it|looks good|correct|do it)$/i.test(lower) ||
      lower === 'yes' || lower === 'confirm')
  ) {
    return mockConfirmConversation(session.conversation_id);
  }

  // 3. Ambiguous AM/PM resolution
  if (session.awaiting_ampm_for_hour !== null) {
    const hour = session.awaiting_ampm_for_hour;
    let resolvedHour: number | null = null;
    if (lower.includes('pm') || lower.includes('p.m.') || lower.includes('evening') || lower.includes('afternoon')) {
      resolvedHour = hour < 12 ? hour + 12 : hour;
    } else if (lower.includes('am') || lower.includes('a.m.') || lower.includes('morning')) {
      resolvedHour = hour === 12 ? 0 : hour;
    }

    if (resolvedHour !== null && session.pending_plan) {
      session.pending_plan.time = `${String(resolvedHour).padStart(2, '0')}:00`;
      session.awaiting_ampm_for_hour = null;
      session.state = 'awaiting_confirmation';
      session.needs_confirmation = true;
      session.clarification_question = null;
      session.confirmation_summary = buildConfirmationSummary(session.pending_plan);
      session.reply_text = session.confirmation_summary;
      return {
        conversation_id: session.conversation_id,
        state: session.state,
        reply_text: session.reply_text,
        clarification_question: null,
        confirmation_summary: session.confirmation_summary,
        pending_plan: session.pending_plan,
        created_plan: null,
        needs_confirmation: true,
        proposal: null,
      };
    }
  }

  // 4. Corrections while in awaiting_confirmation or pending state
  if (session.pending_plan) {
    let modified = false;

    // Check time correction
    const pmMatch = lower.match(/(?:at\s+)?(\d{1,2})\s*(?:pm|p\.m\.)/i);
    const amMatch = lower.match(/(?:at\s+)?(\d{1,2})\s*(?:am|a\.m\.)/i);
    const timeMatch24 = lower.match(/\b([01]?\d|2[0-3]):([0-5]\d)\b/);

    if (pmMatch) {
      const h = parseInt(pmMatch[1], 10);
      const h24 = h < 12 ? h + 12 : h;
      session.pending_plan.time = `${String(h24).padStart(2, '0')}:00`;
      modified = true;
    } else if (amMatch) {
      const h = parseInt(amMatch[1], 10);
      const h24 = h === 12 ? 0 : h;
      session.pending_plan.time = `${String(h24).padStart(2, '0')}:00`;
      modified = true;
    } else if (timeMatch24) {
      session.pending_plan.time = `${String(parseInt(timeMatch24[1], 10)).padStart(2, '0')}:${timeMatch24[2]}`;
      modified = true;
    }

    // Check duration correction
    const durMatch = lower.match(/(\d+)\s*(?:hours?|hrs?|minutes?|mins?)/i);
    if (durMatch) {
      const val = parseInt(durMatch[1], 10);
      if (lower.includes('hour') || lower.includes('hr')) {
        session.pending_plan.duration_minutes = val * 60;
      } else {
        session.pending_plan.duration_minutes = val;
      }
      modified = true;
    } else if (lower.includes('two hours')) {
      session.pending_plan.duration_minutes = 120;
      modified = true;
    } else if (lower.includes('one hour')) {
      session.pending_plan.duration_minutes = 60;
      modified = true;
    }

    // Check date correction
    if (lower.includes('friday')) {
      // Find upcoming Friday
      const now = new Date();
      const currentDay = now.getUTCDay(); // 0 is Sun, 5 is Fri
      let daysUntilFriday = (5 - currentDay + 7) % 7;
      if (daysUntilFriday === 0) daysUntilFriday = 7;
      const target = new Date(now.getTime() + daysUntilFriday * 24 * 60 * 60 * 1000);
      session.pending_plan.date = target.toISOString().split('T')[0];
      modified = true;
    } else if (lower.includes('tomorrow')) {
      const now = new Date();
      const target = new Date(now.getTime() + 24 * 60 * 60 * 1000);
      session.pending_plan.date = target.toISOString().split('T')[0];
      modified = true;
    }

    // Check bare hour (e.g. "at five", "five", "at 5") - negative lookahead prevents matching duration
    const bareHourMatch = lower.match(
      /\b(?:at\s+)?(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d{1,2})(?!\s*(?:hours?|hrs?|minutes?|mins?))\b/i
    );
    const wordNumbers: Record<string, number> = {
      one: 1, two: 2, three: 3, four: 4, five: 5, six: 6,
      seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12
    };
    if (bareHourMatch && !pmMatch && !amMatch && !timeMatch24 && !durMatch && !lower.includes('hour') && !lower.includes('minute')) {
      const rawVal = bareHourMatch[1].toLowerCase();
      const num = wordNumbers[rawVal] || parseInt(rawVal, 10);
      if (num >= 1 && num <= 12) {
        session.awaiting_ampm_for_hour = num;
        session.state = 'awaiting_clarification';
        session.needs_confirmation = false;
        session.clarification_question = `Do you mean ${num} AM or ${num} PM?`;
        session.reply_text = session.clarification_question;
        return {
          conversation_id: session.conversation_id,
          state: session.state,
          reply_text: session.reply_text,
          clarification_question: session.clarification_question,
          confirmation_summary: null,
          pending_plan: session.pending_plan,
          created_plan: null,
          needs_confirmation: false,
          proposal: null,
        };
      }
    }

    if (modified) {
      session.state = 'awaiting_confirmation';
      session.needs_confirmation = true;
      session.clarification_question = null;
      session.confirmation_summary = buildConfirmationSummary(session.pending_plan);
      session.reply_text = session.confirmation_summary;
      return {
        conversation_id: session.conversation_id,
        state: session.state,
        reply_text: session.reply_text,
        clarification_question: null,
        confirmation_summary: session.confirmation_summary,
        pending_plan: session.pending_plan,
        created_plan: null,
        needs_confirmation: true,
        proposal: null,
      };
    }
  }

  // 5. Initial interpretation of user request
  const parsed = mockParsePlan(message, { language: 'en' });
  if (parsed.intent === 'unsupported') {
    session.state = 'unsupported';
    session.reply_text = "I couldn't identify an activity to schedule. Please specify a task you would like to plan.";
    return {
      conversation_id: session.conversation_id,
      state: 'unsupported',
      reply_text: session.reply_text,
      clarification_question: null,
      confirmation_summary: null,
      pending_plan: null,
      created_plan: null,
      needs_confirmation: false,
      proposal: null,
    };
  }

  // Calculate target date (default tomorrow if "tomorrow" mentioned, else today)
  let planDate = getLocalCurrentDate();
  if (lower.includes('tomorrow')) {
    const now = new Date();
    const target = new Date(now.getTime() + 24 * 60 * 60 * 1000);
    planDate = target.toISOString().split('T')[0];
  } else if (lower.includes('friday')) {
    const now = new Date();
    const currentDay = now.getUTCDay();
    let daysUntilFriday = (5 - currentDay + 7) % 7;
    if (daysUntilFriday === 0) daysUntilFriday = 7;
    const target = new Date(now.getTime() + daysUntilFriday * 24 * 60 * 60 * 1000);
    planDate = target.toISOString().split('T')[0];
  }

  // Initial title & category
  const title = parsed.title || 'Study Session';
  const category = parsed.category || 'study';

  session.pending_plan = {
    title,
    category,
    date: planDate,
    time: null,
    duration_minutes: parsed.duration_minutes ?? 60,
    recurrence: null,
    needs_weather_check: parsed.needs_weather_check,
  };

  // Check if time is specified
  const hasTime = parsed.intent === 'create_plan' && parsed.time;
  if (!hasTime) {
    session.state = 'awaiting_clarification';
    session.needs_confirmation = false;
    session.clarification_question = 'What time would you like to start?';
    session.reply_text = session.clarification_question;
    return {
      conversation_id: session.conversation_id,
      state: session.state,
      reply_text: session.reply_text,
      clarification_question: session.clarification_question,
      confirmation_summary: null,
      pending_plan: session.pending_plan,
      created_plan: null,
      needs_confirmation: false,
      proposal: null,
    };
  }

  session.pending_plan.time = parsed.time;
  session.state = 'awaiting_confirmation';
  session.needs_confirmation = true;
  session.clarification_question = null;
  session.confirmation_summary = buildConfirmationSummary(session.pending_plan);
  session.reply_text = session.confirmation_summary;

  return {
    conversation_id: session.conversation_id,
    state: session.state,
    reply_text: session.reply_text,
    clarification_question: null,
    confirmation_summary: session.confirmation_summary,
    pending_plan: session.pending_plan,
    created_plan: null,
    needs_confirmation: true,
    proposal: null,
  };
}

export function mockConfirmConversation(
  conversationId?: string | null,
  idempotencyKey?: string
): ConversationResponse {
  const convId = conversationId || lastActiveMockConversationId;
  const session = convId ? mockConversationSessions.get(convId) : null;

  if (!session || !session.pending_plan) {
    throw new ApiError('No active pending plan to confirm.', 400, 'bad_request');
  }

  if (session.state === 'completed' && session.created_plan) {
    // Idempotent return of already created plan
    return {
      conversation_id: session.conversation_id,
      state: 'completed',
      reply_text: `I have already scheduled your plan: ${session.created_plan.title}.`,
      clarification_question: null,
      confirmation_summary: null,
      pending_plan: session.pending_plan,
      created_plan: session.created_plan,
      needs_confirmation: false,
      proposal: null,
    };
  }

  const key = idempotencyKey || generateIdempotencyKey();
  const created = mockSavePlan(
    {
      intent: 'create_plan',
      title: session.pending_plan.title,
      category: session.pending_plan.category,
      date: session.pending_plan.date,
      time: session.pending_plan.time,
      duration_minutes: session.pending_plan.duration_minutes,
      recurrence: session.pending_plan.recurrence,
      language: 'en',
      needs_weather_check: session.pending_plan.needs_weather_check,
      clarification_question: null,
      confidence: 1.0,
    },
    key
  );

  session.state = 'completed';
  session.created_plan = created;
  session.needs_confirmation = false;
  session.reply_text = `I have scheduled your plan: ${created.title} on ${session.pending_plan.date} at ${formatTime12h(session.pending_plan.time || '18:00')}.`;

  return {
    conversation_id: session.conversation_id,
    state: 'completed',
    reply_text: session.reply_text,
    clarification_question: null,
    confirmation_summary: null,
    pending_plan: session.pending_plan,
    created_plan: created,
    needs_confirmation: false,
    proposal: null,
  };
}

export function mockCancelConversation(conversationId?: string | null): ConversationResponse {
  const convId = conversationId || lastActiveMockConversationId;
  const session = convId ? mockConversationSessions.get(convId) : null;

  if (!session) {
    return {
      conversation_id: convId || generateIdempotencyKey(),
      state: 'cancelled',
      reply_text: 'Plan creation has been cancelled. No plan was saved.',
      clarification_question: null,
      confirmation_summary: null,
      pending_plan: null,
      created_plan: null,
      needs_confirmation: false,
      proposal: null,
    };
  }

  session.state = 'cancelled';
  session.pending_plan = null;
  session.needs_confirmation = false;
  session.clarification_question = null;
  session.confirmation_summary = null;
  session.reply_text = 'Plan creation has been cancelled. No plan was saved.';

  return {
    conversation_id: session.conversation_id,
    state: 'cancelled',
    reply_text: session.reply_text,
    clarification_question: null,
    confirmation_summary: null,
    pending_plan: null,
    created_plan: null,
    needs_confirmation: false,
    proposal: null,
  };
}

export function mockGetActiveConversation(): { active: boolean; conversation: ConversationResponse | null } {
  if (!lastActiveMockConversationId) {
    return { active: false, conversation: null };
  }
  const session = mockConversationSessions.get(lastActiveMockConversationId);
  if (!session || session.state === 'completed' || session.state === 'cancelled') {
    return { active: false, conversation: null };
  }
  return {
    active: true,
    conversation: {
      conversation_id: session.conversation_id,
      state: session.state,
      reply_text: session.reply_text,
      clarification_question: session.clarification_question,
      confirmation_summary: session.confirmation_summary,
      pending_plan: session.pending_plan,
      created_plan: session.created_plan,
      needs_confirmation: session.needs_confirmation,
      proposal: session.proposal,
    },
  };
}

/**
 * Sends a natural language message to the backend conversation orchestration engine.
 */
export async function sendConversationMessage(
  message: string,
  conversationId?: string | null,
  options?: { mockMode?: boolean; language?: 'en' | 'tr' }
): Promise<ConversationResponse> {
  const trimmed = message.trim();
  if (!trimmed) {
    throw new ApiError('Message cannot be empty.', 422, 'validation_error');
  }

  if (options?.mockMode) {
    await new Promise((r) => setTimeout(r, 200));
    return mockSendConversationMessage(trimmed, conversationId, options);
  }

  const payload: ConversationRequest = {
    message: trimmed,
    conversation_id: conversationId ?? null,
    language: options?.language || 'en',
  };

  return apiFetch<ConversationResponse>('/conversation', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Confirms and persists the active pending plan.
 */
export async function confirmConversation(
  conversationId?: string | null,
  options?: { mockMode?: boolean; idempotencyKey?: string }
): Promise<ConversationResponse> {
  if (options?.mockMode) {
    await new Promise((r) => setTimeout(r, 200));
    return mockConfirmConversation(conversationId, options?.idempotencyKey);
  }

  return apiFetch<ConversationResponse>('/conversation/confirm', {
    method: 'POST',
    headers: options?.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : undefined,
    body: JSON.stringify({ conversation_id: conversationId ?? null }),
  });
}

/**
 * Cancels the active pending plan.
 */
export async function cancelConversation(
  conversationId?: string | null,
  options?: { mockMode?: boolean }
): Promise<ConversationResponse> {
  if (options?.mockMode) {
    await new Promise((r) => setTimeout(r, 200));
    return mockCancelConversation(conversationId);
  }

  return apiFetch<ConversationResponse>('/conversation/cancel', {
    method: 'POST',
    body: JSON.stringify({ conversation_id: conversationId ?? null }),
  });
}

/**
 * Gets the active pending conversation if one exists.
 */
export async function getActiveConversation(
  options?: { mockMode?: boolean }
): Promise<{ active: boolean; conversation: ConversationResponse | null }> {
  if (options?.mockMode) {
    return mockGetActiveConversation();
  }

  return apiFetch<{ active: boolean; conversation: ConversationResponse | null }>('/conversation/active', {
    method: 'GET',
  });
}

