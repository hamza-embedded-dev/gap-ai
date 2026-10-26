import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, ClipboardList, Pencil, RotateCcw, Repeat, Search, X } from 'lucide-react';
import { listPlans } from '../api/plans';
import { OutcomeButtons } from '../components/OutcomeButtons';
import type { Plan, PlanOutcome } from '../types/plan';
import {
  countActivePlanFilters,
  DEFAULT_PLAN_FILTERS,
  getPlanCategories,
  sortAndFilterPlans,
  type PlanFilters,
  type PlanSort,
} from '../utils/planFilters';
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

const STATUS_OPTIONS: Array<{ value: PlanFilters['status']; label: string }> = [
  { value: 'all', label: 'All statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'done', label: 'Completed' },
  { value: 'postponed', label: 'Postponed' },
  { value: 'skipped', label: 'Skipped' },
];

const TIME_OPTIONS: Array<{ value: PlanFilters['time']; label: string }> = [
  { value: 'all', label: 'Any time' },
  { value: 'today', label: 'Today' },
  { value: 'tomorrow', label: 'Tomorrow' },
  { value: 'this_week', label: 'This week' },
  { value: 'past', label: 'Past' },
  { value: 'future', label: 'Future' },
];

const SORT_OPTIONS: Array<{ value: PlanSort; label: string }> = [
  { value: 'created_newest', label: 'Newest created' },
  { value: 'created_oldest', label: 'Oldest created' },
  { value: 'start_nearest', label: 'Plan date: nearest' },
  { value: 'start_farthest', label: 'Plan date: farthest' },
];

export function PlanList({ token, onRequireToken, onNavigateCreate }: PlanListProps) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Controlled mock mode (default: false / Live Backend API)
  const [mockMode, setMockMode] = useState<boolean>(false);

  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);
  const [sort, setSort] = useState<PlanSort>('created_newest');
  const [filters, setFilters] = useState<PlanFilters>(DEFAULT_PLAN_FILTERS);

  const filteredPlans = sortAndFilterPlans(plans, filters, sort);
  const activeFilterCount = countActivePlanFilters(filters);
  const categories = getPlanCategories(plans);

  const clearFilters = () => {
    setFilters(DEFAULT_PLAN_FILTERS);
    setSort('created_newest');
  };

  const statusLabel = STATUS_OPTIONS.find((option) => option.value === filters.status)?.label ?? filters.status;
  const timeLabel = TIME_OPTIONS.find((option) => option.value === filters.time)?.label ?? filters.time;

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

      {!isLoading && !errorMessage && plans.length > 0 && (
        <section className="plan-discovery" aria-label="Search, sort and filter plans">
          <div className="plan-discovery-topline">
            <label className="plan-search-field">
              <Search size={17} aria-hidden="true" />
              <span className="visually-hidden">Search plans</span>
              <input
                type="search"
                value={filters.search}
                onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))}
                placeholder="Search plans…"
                aria-label="Search plans by title or description"
              />
            </label>
            <label className="plan-sort-field">
              <span>Sort by</span>
              <select value={sort} onChange={(event) => setSort(event.target.value as PlanSort)}>
                {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
          </div>

          <div className="plan-filter-panel">
            <div className="plan-filter-heading">
              <div>
                <h3>Filters</h3>
                <p>{activeFilterCount} active {activeFilterCount === 1 ? 'filter' : 'filters'}</p>
              </div>
              <button type="button" className="plan-filter-clear" onClick={clearFilters} disabled={activeFilterCount === 0 && sort === 'created_newest'}>
                Clear filters
              </button>
            </div>
            <div className="plan-filter-controls">
              <label>
                <span>Status</span>
                <select value={filters.status} onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value as PlanFilters['status'] }))}>
                  {STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
              <label>
                <span>Time</span>
                <select value={filters.time} onChange={(event) => setFilters((current) => ({ ...current, time: event.target.value as PlanFilters['time'] }))}>
                  {TIME_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
              <label>
                <span>Category</span>
                <select value={filters.category} onChange={(event) => setFilters((current) => ({ ...current, category: event.target.value }))}>
                  <option value="all">All categories</option>
                  {categories.map((category) => <option key={category} value={category}>{category}</option>)}
                </select>
              </label>
            </div>

            {activeFilterCount > 0 && (
              <div className="plan-active-filters" aria-label="Active filters">
                {filters.search.trim() && (
                  <button type="button" className="plan-filter-chip" onClick={() => setFilters((current) => ({ ...current, search: '' }))} aria-label="Remove search filter">
                    Search: {filters.search.trim()} <X size={13} aria-hidden="true" />
                  </button>
                )}
                {filters.status !== 'all' && (
                  <button type="button" className="plan-filter-chip" onClick={() => setFilters((current) => ({ ...current, status: 'all' }))} aria-label={`Remove status filter ${statusLabel}`}>
                    Status: {statusLabel} <X size={13} aria-hidden="true" />
                  </button>
                )}
                {filters.time !== 'all' && (
                  <button type="button" className="plan-filter-chip" onClick={() => setFilters((current) => ({ ...current, time: 'all' }))} aria-label={`Remove time filter ${timeLabel}`}>
                    Time: {timeLabel} <X size={13} aria-hidden="true" />
                  </button>
                )}
                {filters.category !== 'all' && (
                  <button type="button" className="plan-filter-chip" onClick={() => setFilters((current) => ({ ...current, category: 'all' }))} aria-label={`Remove category filter ${filters.category}`}>
                    Category: {filters.category} <X size={13} aria-hidden="true" />
                  </button>
                )}
              </div>
            )}
          </div>
          <p className="plan-result-count" role="status" aria-live="polite">
            Showing {filteredPlans.length} of {plans.length} {plans.length === 1 ? 'plan' : 'plans'}
          </p>
        </section>
      )}

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
      {!isLoading && !errorMessage && plans.length > 0 && filteredPlans.length === 0 && (
        <div className="plan-filter-empty" role="status">
          <h3>No plans match these filters</h3>
          <p>Try adjusting your search or filters to see more plans.</p>
          <button type="button" className="btn btn-primary" onClick={clearFilters}>Clear filters</button>
        </div>
      )}

      {!isLoading && !errorMessage && filteredPlans.length > 0 && (
        <div className="plan-cards-stack" id="plan-cards-list">
          {filteredPlans.map((plan) => {
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
