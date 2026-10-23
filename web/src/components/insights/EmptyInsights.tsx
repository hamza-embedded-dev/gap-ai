import React from 'react';
import { BarChart3, RotateCcw } from 'lucide-react';

export interface EmptyInsightsProps {
  periodLabel?: string;
  onRefresh?: () => void;
}

export const EmptyInsights: React.FC<EmptyInsightsProps> = ({
  periodLabel = 'selected period',
  onRefresh,
}) => {
  return (
    <div
      className="empty-insights-card"
      id="empty-insights-state"
      role="region"
      aria-labelledby="empty-insights-title"
    >
      <div className="empty-insights-icon" aria-hidden="true">
        <BarChart3 size={28} aria-hidden="true" />
      </div>
      <h3 className="empty-insights-title" id="empty-insights-title">
        Not enough data
      </h3>
      <p className="empty-insights-desc" id="empty-insights-desc">
        There are not enough completed or reported plans to calculate analytics for{' '}
        <span className="empty-period-highlight">{periodLabel}</span>.
      </p>
      <div className="empty-insights-hint" id="empty-insights-hint">
        Log your daily plans or report outcomes (done, postponed, skipped) to view adherence trends and behavioral insights.
      </div>
      {onRefresh && (
        <button
          id="empty-insights-refresh-btn"
          type="button"
          className="btn btn-secondary empty-refresh-btn"
          onClick={onRefresh}
        >
          <RotateCcw size={16} aria-hidden="true" />
          <span>Check Again</span>
        </button>
      )}
    </div>
  );
};

export default EmptyInsights;
