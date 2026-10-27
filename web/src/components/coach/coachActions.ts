import type { RecommendationCard, RecommendationFeedbackRequest } from '../../api/insights.ts';
import type { ParsedPlan, Plan } from '../../types/plan.ts';

/** Minimal API surface the Coach needs; real implementations are injected by the page. */
export interface CoachDeps {
  submitFeedback: (input: RecommendationFeedbackRequest) => Promise<void>;
  createPlan: (plan: ParsedPlan, idempotencyKey: string) => Promise<Plan>;
  confirm: (message: string) => boolean;
  newKey: () => string;
  now?: () => Date;
}

export type CoachRating = 'useful' | 'not_useful';

export const DEFAULT_DISCOVERY_DURATION = 20;

export function pad2(value: number): string {
  return String(value).padStart(2, '0');
}

export function formatLocalDate(now: Date): string {
  return `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}`;
}

export function formatLocalTime(now: Date): string {
  return `${pad2(now.getHours())}:${pad2(now.getMinutes())}`;
}

export function clampDuration(value: number): number {
  return Math.max(5, Math.min(1440, Number(value) || 5));
}

export function effectiveDuration(card: RecommendationCard, durations: Record<string, number>): number {
  return durations[card.id] ?? card.duration_minutes ?? DEFAULT_DISCOVERY_DURATION;
}

/** POST /recommendations/feedback with accepted + rating. Returns the success message. */
export async function rateCard(deps: CoachDeps, card: RecommendationCard, rating: CoachRating): Promise<string> {
  await deps.submitFeedback({ recommendation_id: card.id, action: 'accepted', rating });
  return rating === 'useful'
    ? 'Thanks! Marked as useful. We will prioritize similar ideas.'
    : 'Thanks! Marked as not useful. We will show fewer ideas like this.';
}

/** Persists a dismissal (no rating, per the API contract). */
export async function dismissCard(deps: CoachDeps, card: RecommendationCard): Promise<string> {
  await deps.submitFeedback({ recommendation_id: card.id, action: 'dismissed' });
  return 'Got it. This idea will be hidden for 30 days.';
}

/** Persists a modified discovery duration in payload.duration_minutes. */
export async function saveDuration(deps: CoachDeps, card: RecommendationCard, minutes: number): Promise<string> {
  await deps.submitFeedback({ recommendation_id: card.id, action: 'modified', payload: { duration_minutes: minutes } });
  return `Duration saved: ${minutes} minutes.`;
}

/**
 * Adds a discovery idea to My Plans through the existing idempotent POST /plans path.
 * Requires browser confirmation; a repeated attempt for the same card reuses its idempotency key.
 * Returns the success message, or null when the user cancelled.
 */
export async function addToPlans(
  deps: CoachDeps,
  card: RecommendationCard,
  minutes: number,
  keys: Map<string, string>,
): Promise<string | null> {
  const now = (deps.now ?? (() => new Date()))();
  const date = formatLocalDate(now);
  const time = formatLocalTime(now);
  if (!deps.confirm(`Add \u201c${card.title}\u201d to My Plans for today at ${time} (${minutes} minutes)?`)) return null;
  let key = keys.get(card.id);
  if (!key) {
    key = deps.newKey();
    keys.set(card.id, key);
  }
  await deps.createPlan(
    {
      intent: 'create_plan',
      title: card.title,
      category: 'personal',
      date,
      time,
      duration_minutes: minutes,
      recurrence: null,
      language: 'en',
      needs_weather_check: false,
      clarification_question: null,
      confidence: 1,
    },
    key,
  );
  await deps.submitFeedback({ recommendation_id: card.id, action: 'accepted' });
  return `Added \u201c${card.title}\u201d to My Plans.`;
}

/** "Show another idea": rotate the returned cards without changing their stored order. */
export function rotateCards(cards: RecommendationCard[]): RecommendationCard[] {
  return cards.length > 1 ? [...cards.slice(1), cards[0]] : cards;
}

/** The Coach never shows more than three cards. */
export function visibleCards(cards: RecommendationCard[]): RecommendationCard[] {
  return cards.slice(0, 3);
}

export interface CoachErrorData {
  message: string;
  statusCode?: number;
  errorType?: string;
}

export interface CoachState {
  status: 'loading' | 'ready' | 'error';
  cards: RecommendationCard[];
  ratings: Record<string, CoachRating>;
  durations: Record<string, number>;
  whyOpen: Record<string, boolean>;
  busyId: string | null;
  notice: string | null;
  actionError: string | null;
  error: CoachErrorData | null;
}

export type CoachEvent =
  | { type: 'load_start' }
  | { type: 'load_ok'; cards: RecommendationCard[] }
  | { type: 'load_fail'; error: CoachErrorData }
  | { type: 'action_start'; id: string }
  | { type: 'action_ok'; notice: string | null }
  | { type: 'action_fail'; message: string }
  | { type: 'rated'; id: string; rating: CoachRating }
  | { type: 'dismissed'; id: string }
  | { type: 'rotate' }
  | { type: 'set_duration'; id: string; minutes: number }
  | { type: 'toggle_why'; id: string };

export const initialCoachState: CoachState = {
  status: 'loading',
  cards: [],
  ratings: {},
  durations: {},
  whyOpen: {},
  busyId: null,
  notice: null,
  actionError: null,
  error: null,
};

export function coachReducer(state: CoachState, event: CoachEvent): CoachState {
  switch (event.type) {
    case 'load_start':
      return { ...state, status: 'loading', error: null, notice: null, actionError: null };
    case 'load_ok':
      return { ...state, status: 'ready', cards: event.cards, error: null };
    case 'load_fail':
      return { ...state, status: 'error', cards: [], error: event.error };
    case 'action_start':
      return { ...state, busyId: event.id, notice: null, actionError: null };
    case 'action_ok':
      return { ...state, busyId: null, notice: event.notice ?? state.notice };
    case 'action_fail':
      return { ...state, busyId: null, actionError: event.message };
    case 'rated':
      return { ...state, ratings: { ...state.ratings, [event.id]: event.rating } };
    case 'dismissed':
      return { ...state, cards: state.cards.filter((c) => c.id !== event.id) };
    case 'rotate':
      return { ...state, cards: rotateCards(state.cards) };
    case 'set_duration':
      return { ...state, durations: { ...state.durations, [event.id]: clampDuration(event.minutes) } };
    case 'toggle_why':
      return { ...state, whyOpen: { ...state.whyOpen, [event.id]: !state.whyOpen[event.id] } };
    default:
      return state;
  }
}
