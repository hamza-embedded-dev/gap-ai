/**
 * GAP-AI Plan and Parse Types
 *
 * Single source of truth for frontend plan types, strictly conforming to:
 * - ai/schema.json (ParsedPlan)
 * - docs/api-contract.md (Plan, ParseRequest, PlanCreateRequest)
 */

export type PlanIntent = 'create_plan' | 'clarify' | 'unsupported';

export type PlanCategory =
  | 'sport'
  | 'study'
  | 'work'
  | 'meeting'
  | 'health'
  | 'social'
  | 'personal'
  | 'other'
  | null;

export type PlanSource = 'text' | 'voice' | 'device';

export type OutcomeStatus = 'done' | 'postponed' | 'skipped';

export type OutcomeReportedVia = 'web' | 'device' | 'auto';

/**
 * ParsedPlan structure matching ai/schema.json.
 * All 11 keys are required in the schema.
 */
export interface ParsedPlan {
  intent: PlanIntent;
  title: string | null;
  category: PlanCategory;
  date: string | null; // "YYYY-MM-DD"
  time: string | null; // "HH:MM"
  duration_minutes: number | null; // 5 - 1440
  recurrence: string | null;
  language: 'tr' | 'en';
  needs_weather_check: boolean;
  clarification_question: string | null;
  confidence: number; // 0.0 - 1.0
}

/**
 * Payload sent to POST /parse
 * Note: backend uses extra="forbid", so never send unexpected properties.
 */
export interface ParseRequest {
  text: string;
  current_date: string; // "YYYY-MM-DD"
  language?: 'tr' | 'en';
  timezone?: string;
}

/**
 * Payload sent to POST /plans
 */
export interface PlanCreateRequest {
  parsed_plan: ParsedPlan;
  source: PlanSource;
}

/**
 * Outcome event structure from docs/api-contract.md
 */
export interface PlanOutcome {
  id: string;
  plan_id: string;
  status: OutcomeStatus;
  actual_start: string | null;
  postponed_to: string | null;
  note: string | null;
  reported_via: OutcomeReportedVia;
  reported_at: string;
}

/**
 * Plan object returned by POST /plans and GET /plans
 */
export interface Plan {
  id: string;
  title: string;
  category: string;
  planned_start: string;
  planned_end: string;
  recurrence_rule: string | null;
  source: PlanSource;
  created_at: string;
  latest_outcome: PlanOutcome | null;
}
