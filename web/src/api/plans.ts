import { apiFetch, ApiError } from './client.ts';
import type {
  ParsedPlan,
  ParseRequest,
  Plan,
  PlanCreateRequest,
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

export interface ParsePlanOptions {
  language?: 'tr' | 'en';
  mockMode?: boolean;
}

export interface SavePlanOptions {
  mockMode?: boolean;
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
  let title = 'Planlanan Aktivite';
  let needsWeather = false;

  if (SPORT_KEYWORDS.some((k) => folded.includes(k))) {
    category = 'sport';
    title = 'Koşu';
    needsWeather = true;
  } else if (STUDY_KEYWORDS.some((k) => folded.includes(k))) {
    category = 'study';
    title = 'Ders Çalışma';
  } else if (MEETING_KEYWORDS.some((k) => folded.includes(k))) {
    category = 'meeting';
    title = 'Toplantı';
  } else if (HEALTH_KEYWORDS.some((k) => folded.includes(k))) {
    category = 'health';
    title = 'Sağlık Randevusu';
  } else if (SOCIAL_KEYWORDS.some((k) => folded.includes(k))) {
    category = 'social';
    title = 'Sosyal Buluşma';
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
    const question =
      category === 'sport'
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
    throw new ApiError('Plan metni boş bırakılamaz.', 422, 'validation_error');
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
 * Saves a confirmed plan via POST /plans with an Idempotency-Key header.
 *
 * @throws {ApiError} when validation fails or backend rejects the request.
 */
export async function createPlan(
  parsedPlan: ParsedPlan,
  idempotencyKey: string,
  options?: SavePlanOptions
): Promise<Plan> {
  if (parsedPlan.intent !== 'create_plan') {
    throw new ApiError(
      'Yalnızca create_plan niyetine sahip planlar kaydedilebilir.',
      422,
      'validation_error'
    );
  }

  if (!isValidUUID(idempotencyKey)) {
    throw new ApiError(
      'Geçersiz Idempotency-Key formatı: UUID v4 bekleniyor.',
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
