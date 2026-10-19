import { useState } from 'react';
import { reportPlanOutcome } from '../api/plans';
import type { OutcomeStatus, PlanOutcome } from '../types/plan';
import './OutcomeButtons.css';

export interface OutcomeButtonsProps {
  planId: string;
  latestOutcome: PlanOutcome | null;
  onOutcomeReported: (outcome: PlanOutcome) => void;
  mockMode?: boolean;
  disabled?: boolean;
}

const OUTCOME_OPTIONS: Array<{
  status: OutcomeStatus;
  label: string;
  icon: string;
  className: string;
}> = [
  { status: 'done', label: 'Done', icon: '✓', className: 'outcome-btn-done' },
  { status: 'postponed', label: 'Postponed', icon: '⏳', className: 'outcome-btn-postponed' },
  { status: 'skipped', label: 'Skipped', icon: '⏭', className: 'outcome-btn-skipped' },
];

export function OutcomeButtons({
  planId,
  latestOutcome,
  onOutcomeReported,
  mockMode = false,
  disabled = false,
}: OutcomeButtonsProps) {
  const [submittingStatus, setSubmittingStatus] = useState<OutcomeStatus | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSelectOutcome = async (status: OutcomeStatus) => {
    if (submittingStatus !== null || disabled) {
      return;
    }

    setSubmittingStatus(status);
    setErrorMessage(null);

    try {
      // POST /plans/{id}/outcome with reported_via: "web"
      const outcome = await reportPlanOutcome(planId, status, { mockMode });
      // Only upon confirmed success from backend (or mock in mockMode):
      onOutcomeReported(outcome);
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : 'Sonuç kaydedilirken bir hata oluştu. Lütfen tekrar deneyin.';
      setErrorMessage(msg);
      // NOTE: latestOutcome is NOT updated on failure.
    } finally {
      setSubmittingStatus(null);
    }
  };

  const getStatusBadge = () => {
    if (!latestOutcome) {
      return (
        <span className="outcome-badge outcome-badge-none" id={`outcome-badge-${planId}`}>
          Beklemede (Raporlanmadı)
        </span>
      );
    }

    const { status, reported_at } = latestOutcome;
    const formattedDate = reported_at
      ? new Date(reported_at).toLocaleTimeString('tr-TR', {
          hour: '2-digit',
          minute: '2-digit',
        })
      : '';

    switch (status) {
      case 'done':
        return (
          <span className="outcome-badge outcome-badge-done" id={`outcome-badge-${planId}`}>
            ✓ Tamamlandı (Done) {formattedDate && `• ${formattedDate}`}
          </span>
        );
      case 'postponed':
        return (
          <span className="outcome-badge outcome-badge-postponed" id={`outcome-badge-${planId}`}>
            ⏳ Ertelendi (Postponed) {formattedDate && `• ${formattedDate}`}
          </span>
        );
      case 'skipped':
        return (
          <span className="outcome-badge outcome-badge-skipped" id={`outcome-badge-${planId}`}>
            ⏭ Atlandı (Skipped) {formattedDate && `• ${formattedDate}`}
          </span>
        );
      default:
        return null;
    }
  };

  const isCurrentStatus = (status: OutcomeStatus) => {
    return latestOutcome?.status === status;
  };

  return (
    <div className="outcome-container">
      {/* Current Outcome Status Display */}
      <div className="outcome-current-badge-row">
        <span className="outcome-badge-label">Mevcut Durum:</span>
        {getStatusBadge()}
      </div>

      {/* Outcome Selection Buttons */}
      <div className="outcome-btn-group" role="group" aria-label="Sonuç bildir">
        {OUTCOME_OPTIONS.map((opt) => {
          const isSubmittingThis = submittingStatus === opt.status;
          const isAnySubmitting = submittingStatus !== null;
          const isActive = isCurrentStatus(opt.status);

          return (
            <button
              key={opt.status}
              type="button"
              id={`btn-${opt.status}-${planId}`}
              className={`outcome-btn ${opt.className} ${isActive ? 'outcome-btn-active' : ''}`}
              onClick={() => handleSelectOutcome(opt.status)}
              disabled={disabled || isAnySubmitting}
              title={`${opt.label} olarak bildir`}
              aria-pressed={isActive}
            >
              {isSubmittingThis ? (
                <>
                  <span className="outcome-spinner" aria-hidden="true" />
                  <span>Kaydediliyor...</span>
                </>
              ) : (
                <>
                  <span aria-hidden="true">{opt.icon}</span>
                  <span>{opt.label}</span>
                </>
              )}
            </button>
          );
        })}
      </div>

      {/* Inline Error Message */}
      {errorMessage && (
        <div className="outcome-error-alert" role="alert" id={`outcome-error-${planId}`}>
          <span>⚠️ {errorMessage}</span>
          <button
            type="button"
            className="outcome-error-close"
            onClick={() => setErrorMessage(null)}
            title="Kapat"
            aria-label="Hatayı kapat"
          >
            ×
          </button>
        </div>
      )}
    </div>
  );
}
