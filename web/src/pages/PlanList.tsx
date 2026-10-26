import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, ClipboardList, Pencil, RotateCcw, Repeat } from 'lucide-react';
import { listPlans } from '../api/plans';
import { fetchPlanSuggestion } from '../api/plans';
import type { PlanSuggestion } from '../api/plans';
import { OutcomeButtons } from '../components/OutcomeButtons';
import type { Plan, PlanOutcome } from '../types/plan';
import './PlanList.css';

export interface PlanListProps {
  token: string | null;
  onRequireToken?: () => void;
  onNavigateCreate?: () => void;
}

const MOCK_PLAN_TITLES: Record<string, string> = {
  'Sabah Koşusu': 'Morning Run',
  'Haftalık Ekip Senkronizasyonu': 'Weekly Team Sync',
  'GAP-AI Frontend Geliştirme': 'GAP-AI Frontend Development',
  'Akşam Yürüyüşü': 'Evening Walk',
};

function SuggestionCard({ planId, planTitle, refreshKey, enabled }: {
  planId: string;
  planTitle: string;
  refreshKey: string;
  enabled: boolean;
}) {
  const [suggestion, setSuggestion] = useState<PlanSuggestion | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    if (!enabled) {
      setLoading(false);
      return () => { active = false; };
    }
    setLoading(true);
    setError(false);
    void fetchPlanSuggestion(planId)
      .then((value) => { if (active) setSuggestion(value); })
      .catch(() => { if (active) setError(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [planId, refreshKey, retry, enabled]);

  if (loading) return <div className="suggestion-card" aria-live="polite">Loading your personalized recommendation…</div>;
  if (error) return <div className="suggestion-card" role="alert">
    Recommendation could not be loaded. <button type="button" onClick={() => setRetry((n) => n + 1)}>Retry</button>
  </div>;
  if (!suggestion) return null;
  return <aside className="suggestion-card" aria-label="Personalized recommendation">
    <strong>{planTitle} · Personalized recommendation</strong>
    <p>{suggestion.message}</p>
    {suggestion.evidence.adherence_pct != null && <small>
      Based on {suggestion.evidence.outcome_count ?? ''} outcomes, completion rate: {suggestion.evidence.adherence_pct}%
    </small>}
  </aside>;
}

export function PlanList({ token, onRequireToken, onNavigateCreate }: PlanListProps) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Controlled mock mode (default: false / Live Backend API)
  const [mockMode, setMockMode] = useState<boolean>(false);

  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);

  const loadPlans = useCallback(() => {
    setIsLoading(true);
    setRefreshTrigger((prev) => prev + 1);
  }, []);

  useEffect(() => {
    let ignore = false;

    async function executeFetch() {
      if (!token && !mockMode) {
        if (!ignore) {
          setPlans([]);
          setErrorMessage('Sign in with Demo & Auth to view your plans.');
          setIsLoading(false);
        }
        return;
      }

      try {
        const items = await listPlans({ mockMode });
        if (!ignore) {
          setPlans(items);
          setErrorMessage(null);
        }
      } catch (err) {
        if (!ignore) {
          const msg =
            err instanceof Error
              ? err.message
              : 'An unexpected error occurred while loading plans.';
          setErrorMessage(msg);
          setPlans([]);
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    }

    void executeFetch();

    return () => {
      ignore = true;
    };
  }, [token, mockMode, refreshTrigger]);

  const handleOutcomeReported = (planId: string, outcome: PlanOutcome) => {
    setPlans((prev) =>
      prev.map((plan) => (plan.id === planId ? { ...plan, latest_outcome: outcome } : plan))
    );
  };

  const formatDateTime = (isoString: string) => {
    try {
      const d = new Date(isoString);
      if (isNaN(d.getTime())) return isoString;
      return d.toLocaleString('en-US', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoString;
    }
  };

  const formatTimeOnly = (isoString: string) => {
    try {
      const d = new Date(isoString);
      if (isNaN(d.getTime())) return isoString;
      return d.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="plan-list-wrapper">
      {/* API mode controls */}
      <div className="mode-toggle-bar">
        <div className="mode-toggle-left">
          <span>Mode:</span>
          <span
            className={`mode-badge ${mockMode ? 'mode-mock' : 'mode-live'}`}
            id="plan-list-mode-badge"
          >
            {mockMode ? 'Test / Mock Mode' : 'Live Backend API'}
          </span>
        </div>
        <button
          type="button"
          className="mode-toggle-btn"
          id="toggle-plan-list-mock-btn"
          onClick={() => {
            const nextMode = !mockMode;
            setMockMode(nextMode);
          }}
        >
          {mockMode ? 'Switch to Live API' : 'Switch to Mock Mode'}
        </button>
      </div>

      {/* Header and Actions */}
      <div className="plan-list-header">
        <div className="plan-list-title-group">
          <h2>My Plans</h2>
          {!isLoading && !errorMessage && (
            <span className="plan-count-badge" id="plan-count-badge">
              {plans.length} {plans.length === 1 ? 'plan' : 'plans'}
            </span>
          )}
        </div>

        <div className="plan-list-actions">
          {onNavigateCreate && (
            <button
              type="button"
              className="btn btn-secondary"
              id="header-create-plan-btn"
              onClick={onNavigateCreate}
            >
              <Pencil size={16} aria-hidden="true" />
              Create Plan
            </button>
          )}

          <button
            type="button"
            className="btn-refresh"
            id="refresh-plans-btn"
            onClick={loadPlans}
            disabled={isLoading}
            title="Refresh plans"
          >
            <RotateCcw size={16} aria-hidden="true" />
            <span>{isLoading ? 'Loading...' : 'Refresh'}</span>
          </button>
        </div>
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="plan-list-loading" id="plan-list-loading-state">
          <div className="large-spinner" aria-hidden="true" />
          <p>Loading your plans...</p>
        </div>
      )}

      {/* Error State */}
      {!isLoading && errorMessage && (
        <div className="plan-list-error" role="alert" id="plan-list-error-state">
          <AlertTriangle className="alert-icon" size={28} aria-hidden="true" />
          <h3 className="error-title">Unable to load plans</h3>
          <p className="error-desc">{errorMessage}</p>
          <div style={{ display: 'flex', gap: '10px', marginTop: '8px' }}>
            <button
              type="button"
              className="btn btn-primary"
              id="retry-load-plans-btn"
              onClick={loadPlans}
            >
              Try Again
            </button>
            {!token && onRequireToken && (
              <button
                type="button"
                className="btn btn-secondary"
                id="login-from-plans-btn"
                onClick={onRequireToken}
              >
                Open Demo &amp; Auth
              </button>
            )}
          </div>
        </div>
      )}

      {/* Empty State */}
      {!isLoading && !errorMessage && plans.length === 0 && (
        <div className="plan-list-empty" id="plan-list-empty-state">
          <div className="empty-icon" aria-hidden="true"><ClipboardList size={28} /></div>
          <h3 className="empty-title">No plans yet</h3>
          <p className="empty-desc">
            Create a plan using natural language, or review the sample plans in your demo session.
          </p>
          {onNavigateCreate && (
            <button
              type="button"
              className="btn btn-primary"
              id="empty-create-plan-btn"
              onClick={onNavigateCreate}
            >
              <Pencil size={16} aria-hidden="true" />
              Create Your First Plan
            </button>
          )}
        </div>
      )}

      {/* Plan Card Stack */}
      {!isLoading && !errorMessage && plans.length > 0 && (
        <div className="plan-cards-stack" id="plan-cards-list">
          {plans.map((plan) => {
            const categoryClass = plan.category
              ? `category-${plan.category}`
              : 'category-other';

            return (
              <article
                key={plan.id}
                id={`plan-card-${plan.id}`}
                className="plan-card"
                aria-labelledby={`plan-title-${plan.id}`}
              >
                {/* Header: Title and Badges */}
                <div className="plan-card-header">
                  <div className="plan-card-title-row">
                    <h3 className="plan-title" id={`plan-title-${plan.id}`}>
                      {mockMode ? MOCK_PLAN_TITLES[plan.title] || plan.title : plan.title}
                    </h3>
                    <div className="plan-badges">
                      <span className={`category-tag ${categoryClass}`}>
                        {plan.category || 'Other'}
                      </span>
                      <span className="source-tag">
                        Source: {plan.source === 'voice' ? 'Voice' : plan.source === 'device' ? 'Device' : 'Text'}
                      </span>
                      {plan.recurrence_rule && (
                        <span className="recurrence-badge" title="Recurrence rule">
                          <Repeat size={14} aria-hidden="true" /> {plan.recurrence_rule}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Details Grid */}
                <div className="plan-details-grid">
                  <div className="detail-item">
                    <span className="detail-label">Scheduled start</span>
                    <span className="detail-value">{formatDateTime(plan.planned_start)}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">End</span>
                    <span className="detail-value">{formatTimeOnly(plan.planned_end)}</span>
                  </div>
                </div>

                <SuggestionCard
                  planId={plan.id}
                  planTitle={plan.title}
                  enabled={!mockMode && Boolean(token)}
                  refreshKey={plan.latest_outcome?.reported_at ?? ''}
                />

                {/* Outcome Reporting Section */}
                <div className="plan-outcome-section">
                  <OutcomeButtons
                    planId={plan.id}
                    latestOutcome={plan.latest_outcome}
                    onOutcomeReported={(outcome) => handleOutcomeReported(plan.id, outcome)}
                    mockMode={mockMode}
                    disabled={!token && !mockMode}
                  />
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
