import { apiFetch } from './client';

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
  return apiFetch<InsightsResponse>(`/insights?period=${query}`, {
    method: 'GET',
  });
}
