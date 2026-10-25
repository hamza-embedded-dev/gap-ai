import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { AlertTriangle, ClipboardList, Pencil, RotateCcw, Repeat, Save, Trash2, X } from 'lucide-react';
import { deletePlan, listPlans, updatePlan } from '../api/plans';
import { OutcomeButtons } from '../components/OutcomeButtons';
import type { Plan, PlanOutcome, PlanUpdateRequest } from '../types/plan';
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

const PLAN_CATEGORIES: PlanUpdateRequest['category'][] = [
  'sport', 'study', 'work', 'meeting', 'health', 'social', 'personal', 'other',
];

function toLocalDateTimeInput(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (part: number) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function planEditFormValues(plan: Plan): PlanUpdateRequest {
  return {
    title: plan.title,
    category: plan.category as PlanUpdateRequest['category'],
    planned_start: toLocalDateTimeInput(plan.planned_start),
    planned_end: toLocalDateTimeInput(plan.planned_end),
  };
}

export function PlanList({ token, onRequireToken, onNavigateCreate }: PlanListProps) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Controlled mock mode (default: false / Live Backend API)
  const [mockMode, setMockMode] = useState<boolean>(false);

  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);
  const [editingPlan, setEditingPlan] = useState<Plan | null>(null);
  const [editForm, setEditForm] = useState<PlanUpdateRequest | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [activeMutationId, setActiveMutationId] = useState<string | null>(null);

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

  const openEditDialog = (plan: Plan) => {
    setEditingPlan(plan);
    setEditForm(planEditFormValues(plan));
    setEditError(null);
    setActionError(null);
    setActionNotice(null);
  };

  const closeEditDialog = () => {
    if (activeMutationId) return;
    setEditingPlan(null);
    setEditForm(null);
    setEditError(null);
  };

  const reloadPlansAfterMutation = async () => {
    const refreshed = await listPlans();
    setPlans(refreshed);
  };

  const handleEditSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editingPlan || !editForm) return;

    const start = new Date(editForm.planned_start);
    const end = new Date(editForm.planned_end);
    if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) {
      setEditError('Enter a valid start and end date and time.');
      return;
    }
    if (end <= start) {
      setEditError('End date and time must be after the start.');
      return;
    }

    setEditError(null);
    setActionError(null);
    setActionNotice(null);
    setActiveMutationId(editingPlan.id);
    try {
      const updated = await updatePlan(editingPlan.id, {
        ...editForm,
        title: editForm.title.trim(),
        planned_start: start.toISOString(),
        planned_end: end.toISOString(),
      });
      setPlans((current) => current.map((plan) => plan.id === updated.id ? updated : plan));
      setEditingPlan(null);
      setEditForm(null);
      setActionNotice('Plan updated.');
      try {
        await reloadPlansAfterMutation();
      } catch {
        setActionError('The plan was updated, but the list could not be refreshed. Use Refresh to reload it.');
      }
    } catch (error) {
      setEditError(error instanceof Error ? error.message : 'Unable to update this plan. Try again.');
    } finally {
      setActiveMutationId(null);
    }
  };

  const handleDelete = async (plan: Plan) => {
    if (!window.confirm(
      `Delete “${plan.title}”? Its outcome history and related recommendations will also be permanently deleted. This cannot be undone.`
    )) return;

    setActionError(null);
    setActionNotice(null);
    setActiveMutationId(plan.id);
    try {
      await deletePlan(plan.id);
      setPlans((current) => current.filter((item) => item.id !== plan.id));
      setActionNotice(`“${plan.title}” was deleted.`);
      try {
        await reloadPlansAfterMutation();
      } catch {
        setActionError('The plan was deleted, but the list could not be refreshed. Use Refresh to reload it.');
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Unable to delete this plan. Try again.');
    } finally {
      setActiveMutationId(null);
    }
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

      {actionError && <p className="plan-action-error" role="alert">{actionError}</p>}
      {actionNotice && <p className="plan-action-notice" role="status">{actionNotice}</p>}

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
                  <div className="plan-card-actions" aria-label={`Actions for ${plan.title}`}>
                    <button
                      type="button"
                      className="plan-action-button"
                      aria-label={`Edit ${plan.title}`}
                      onClick={() => openEditDialog(plan)}
                      disabled={!token || mockMode || activeMutationId !== null}
                      title={mockMode ? 'Editing requires the live backend.' : 'Edit plan'}
                    >
                      <Pencil size={15} aria-hidden="true" />
                      <span>Edit</span>
                    </button>
                    <button
                      type="button"
                      className="plan-action-button plan-delete-button"
                      aria-label={`Delete ${plan.title}`}
                      onClick={() => void handleDelete(plan)}
                      disabled={!token || mockMode || activeMutationId !== null}
                      title={mockMode ? 'Deletion requires the live backend.' : 'Delete plan'}
                    >
                      <Trash2 size={15} aria-hidden="true" />
                      <span>Delete</span>
                    </button>
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

      {editingPlan && editForm && (
        <div className="plan-edit-backdrop">
          <section
            className="plan-edit-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="plan-edit-title"
            onKeyDown={(event) => {
              if (event.key === 'Escape') closeEditDialog();
            }}
          >
            <div className="plan-edit-heading">
              <div>
                <h3 id="plan-edit-title">Edit plan</h3>
                <p>Update the saved plan details.</p>
              </div>
              <button
                type="button"
                className="plan-dialog-close"
                aria-label="Close edit dialog"
                onClick={closeEditDialog}
                disabled={activeMutationId !== null}
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>
            <form className="plan-edit-form" onSubmit={(event) => void handleEditSubmit(event)}>
              <label>
                Plan title
                <input
                  autoFocus
                  required
                  value={editForm.title}
                  onChange={(event) => setEditForm({ ...editForm, title: event.target.value })}
                />
              </label>
              <label>
                Category
                <select
                  value={editForm.category}
                  onChange={(event) => setEditForm({ ...editForm, category: event.target.value as PlanUpdateRequest['category'] })}
                >
                  {PLAN_CATEGORIES.map((category) => <option key={category} value={category}>{category}</option>)}
                </select>
              </label>
              <label>
                Start date and time
                <input
                  type="datetime-local"
                  required
                  value={editForm.planned_start}
                  onChange={(event) => setEditForm({ ...editForm, planned_start: event.target.value })}
                />
              </label>
              <label>
                End date and time
                <input
                  type="datetime-local"
                  required
                  value={editForm.planned_end}
                  onChange={(event) => setEditForm({ ...editForm, planned_end: event.target.value })}
                />
              </label>
              {editError && <p className="plan-edit-error" role="alert">{editError}</p>}
              <div className="plan-edit-actions">
                <button type="button" className="btn btn-secondary" onClick={closeEditDialog} disabled={activeMutationId !== null}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={activeMutationId !== null}>
                  <Save size={16} aria-hidden="true" />
                  {activeMutationId === editingPlan.id ? 'Saving…' : 'Save changes'}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
