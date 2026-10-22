import { useCallback, useEffect, useState } from 'react';
import { listPlans } from '../api/plans';
import { OutcomeButtons } from '../components/OutcomeButtons';
import type { Plan, PlanOutcome } from '../types/plan';
import './PlanList.css';

export interface PlanListProps {
  token: string | null;
  onRequireToken?: () => void;
  onNavigateCreate?: () => void;
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
          setErrorMessage('Planlarınızı görebilmek için lütfen önce "Try Demo" ile oturum açın.');
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
              : 'Planlar yüklenirken beklenmeyen bir hata oluştu.';
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
      return d.toLocaleString('tr-TR', {
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
      return d.toLocaleTimeString('tr-TR', {
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="plan-list-wrapper">
      {/* Test / Canlı Modu Göstergesi */}
      <div className="mode-toggle-bar">
        <div className="mode-toggle-left">
          <span>Mod:</span>
          <span
            className={`mode-badge ${mockMode ? 'mode-mock' : 'mode-live'}`}
            id="plan-list-mode-badge"
          >
            {mockMode ? '● Test / Mock Modu (B4-1 Bağımsız)' : '● Canlı Backend API'}
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
          {mockMode ? 'Canlı Moda Geç' : 'Test Moduna Geç'}
        </button>
      </div>

      {/* Header and Actions */}
      <div className="plan-list-header">
        <div className="plan-list-title-group">
          <h2>Planlarım</h2>
          {!isLoading && !errorMessage && (
            <span className="plan-count-badge" id="plan-count-badge">
              {plans.length} plan
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
              + Yeni Plan
            </button>
          )}

          <button
            type="button"
            className="btn-refresh"
            id="refresh-plans-btn"
            onClick={loadPlans}
            disabled={isLoading}
            title="Listeyi yenile"
          >
            <span aria-hidden="true">↻</span>
            <span>{isLoading ? 'Yükleniyor...' : 'Yenile'}</span>
          </button>
        </div>
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="plan-list-loading" id="plan-list-loading-state">
          <div className="large-spinner" aria-hidden="true" />
          <p>Planlarınız getiriliyor...</p>
        </div>
      )}

      {/* Error State */}
      {!isLoading && errorMessage && (
        <div className="plan-list-error" role="alert" id="plan-list-error-state">
          <span className="alert-icon" style={{ fontSize: '2rem' }}>⚠️</span>
          <h3 className="error-title">Planlar Yüklenemedi</h3>
          <p className="error-desc">{errorMessage}</p>
          <div style={{ display: 'flex', gap: '10px', marginTop: '8px' }}>
            <button
              type="button"
              className="btn btn-primary"
              id="retry-load-plans-btn"
              onClick={loadPlans}
            >
              Yeniden Dene
            </button>
            {!token && onRequireToken && (
              <button
                type="button"
                className="btn btn-secondary"
                id="login-from-plans-btn"
                onClick={onRequireToken}
              >
                Oturum Aç (Try Demo)
              </button>
            )}
          </div>
        </div>
      )}

      {/* Empty State */}
      {!isLoading && !errorMessage && plans.length === 0 && (
        <div className="plan-list-empty" id="plan-list-empty-state">
          <div className="empty-icon" aria-hidden="true">📋</div>
          <h3 className="empty-title">Henüz Bir Planınız Yok</h3>
          <p className="empty-desc">
            Doğal dilde hedeflerinizi yazarak hemen yeni bir plan oluşturabilir veya demo
            oturumundaki hazır planları inceleyebilirsiniz.
          </p>
          {onNavigateCreate && (
            <button
              type="button"
              className="btn btn-primary"
              id="empty-create-plan-btn"
              onClick={onNavigateCreate}
            >
              ✍️ İlk Planını Oluştur
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
                      {plan.title}
                    </h3>
                    <div className="plan-badges">
                      <span className={`category-tag ${categoryClass}`}>
                        {plan.category || 'Genel'}
                      </span>
                      <span className="source-tag">
                        Kaynak: {plan.source === 'voice' ? 'Sesli' : plan.source === 'device' ? 'Cihaz' : 'Metin'}
                      </span>
                      {plan.recurrence_rule && (
                        <span className="recurrence-badge" title="Yinelenme Kuralı">
                          🔁 {plan.recurrence_rule}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Details Grid */}
                <div className="plan-details-grid">
                  <div className="detail-item">
                    <span className="detail-label">Planlanan Başlangıç</span>
                    <span className="detail-value">{formatDateTime(plan.planned_start)}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Bitiş</span>
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
