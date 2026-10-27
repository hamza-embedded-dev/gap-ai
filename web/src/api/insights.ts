import { apiFetch } from './client.ts';

export type InsightsPeriod = 'week' | 'last_week' | 'all';

export interface WeekdayStats {
  planned: number;
  done: number;
  postponed?: number;
  skipped?: number;
}

export interface HourStats {
  planned: number;
  done: number;
  postponed?: number;
  skipped?: number;
}

export interface CategoryStats {
  planned: number;
  done: number;
  postponed?: number;
  skipped?: number;
}

export interface PostponedTarget {
  weekday: string;
  hour: number;
  count: number;
}

export interface TrendVsPrev {
  adherence_pct_delta?: number | null;
}

export interface RecommendationCard {
  id: string; title: string; message: string; why: string;
  evidence: Record<string, string | number>;
  confidence: 'moderate' | 'none'; next_step: string;
  source: 'behavior' | 'discovery' | 'contextual'; label: string | null; dedup_key: string | null; duration_minutes: number | null;
}

export interface RecommendationFeedbackRequest {
  recommendation_id: string;
  action: 'accepted' | 'dismissed' | 'modified';
  rating?: 'useful' | 'not_useful' | null;
  payload?: Record<string, unknown>;
}

export async function submitRecommendationFeedback(input: RecommendationFeedbackRequest): Promise<void> {
  await apiFetch('/recommendations/feedback', { method: 'POST', body: JSON.stringify({ rating: null, payload: {}, ...input }) });
}

export interface InsightsResponse {
  period: InsightsPeriod;
  planned: number;
  done: number;
  postponed: number;
  skipped: number;
  unreported: number;
  adherence_pct: number | null;
  avg_start_delay_min?: number | null;
  by_weekday?: Record<string, WeekdayStats>;
  by_hour?: Record<string, HourStats>;
  by_category?: Record<string, CategoryStats>;
  postponed_targets?: PostponedTarget[];
  trend_vs_prev?: TrendVsPrev | null;
  narrative?: string | null;
  is_demo?: boolean;
  data_label?: 'real' | 'demo' | string;
  recommendations?: RecommendationCard[];
}

/**
 * Calls the `GET /insights?period=${period}` backend endpoint
 * to fetch deterministic behavior analytics and adherence metrics.
 *
 * @param period Insights timeframe: 'week' (default), 'last_week', or 'all'
 * @returns {Promise<InsightsResponse>} Insights response object
 */
export async function fetchInsights(
  period: InsightsPeriod = 'week'
): Promise<InsightsResponse> {
  const query = encodeURIComponent(period);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  try {
    return await apiFetch<InsightsResponse>(`/insights?period=${query}`, {
      method: 'GET', signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}
