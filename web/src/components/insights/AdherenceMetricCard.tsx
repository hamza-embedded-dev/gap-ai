import React from 'react';
import type { InsightsResponse } from '../../api/insights';

export interface AdherenceMetricCardProps {
  insights: InsightsResponse;
}

export const AdherenceMetricCard: React.FC<AdherenceMetricCardProps> = ({ insights }) => {
  const adherence = insights.adherence_pct;
  const hasAdherence = adherence !== null && adherence !== undefined && !Number.isNaN(adherence);
  const formattedPct = hasAdherence ? adherence.toFixed(1) : '--';

  // SVG circle gauge parameters:
  const radius = 54;
  const stroke = 10;
  const normalizedRadius = radius - stroke / 2;
  const circumference = normalizedRadius * 2 * Math.PI;
  const strokeDashoffset = hasAdherence
    ? circumference - (Math.min(100, Math.max(0, adherence)) / 100) * circumference
    : circumference;

  const trendDelta = insights.trend_vs_prev?.adherence_pct_delta;
  const hasTrend = trendDelta !== null && trendDelta !== undefined && !Number.isNaN(trendDelta);

  return (
    <section className="insights-metric-card" id="adherence-card">
      <div className="metric-header">
        <div>
          <span className="metric-eyebrow">Adherence Metric</span>
          <h2 className="metric-title">Overall Plan Adherence</h2>
        </div>
        {hasTrend && (
          <div
            className={`trend-pill ${trendDelta >= 0 ? 'trend-up' : 'trend-down'}`}
            title="Change vs. previous period"
          >
            <span className="trend-arrow" aria-hidden="true">
              {trendDelta >= 0 ? '↑' : '↓'}
            </span>
            <span className="trend-text">
              {trendDelta >= 0 ? `+${trendDelta.toFixed(1)}%` : `${trendDelta.toFixed(1)}%`}
            </span>
            <span className="trend-sub">vs. previous period</span>
          </div>
        )}
      </div>

      <div className="metric-body">
        {/* Circular Progress Gauge */}
        <div className="gauge-wrapper" aria-label={`Adherence: ${formattedPct}%`}>
          <svg height={radius * 2} width={radius * 2} className="gauge-svg">
            <circle
              className="gauge-bg"
              stroke="var(--color-primary-subtle, #f5f3ff)"
              strokeWidth={stroke}
              fill="transparent"
              r={normalizedRadius}
              cx={radius}
              cy={radius}
            />
            <circle
              className="gauge-progress"
              stroke="var(--color-primary, #7c3aed)"
              strokeWidth={stroke}
              strokeDasharray={`${circumference} ${circumference}`}
              style={{ strokeDashoffset }}
              strokeLinecap="round"
              fill="transparent"
              r={normalizedRadius}
              cx={radius}
              cy={radius}
            />
          </svg>
          <div className="gauge-center">
            <span className="gauge-value" id="adherence-percentage-value">
              {formattedPct}%
            </span>
            <span className="gauge-label">Adherence Rate</span>
          </div>
        </div>

        {/* Breakdown Statistics Grid */}
        <div className="stats-grid">
          <div className="stat-box stat-planned">
            <span className="stat-label">Total Planned</span>
            <span className="stat-number" id="stat-planned-count">
              {insights.planned}
            </span>
          </div>

          <div className="stat-box stat-done">
            <div className="stat-indicator indicator-done" aria-hidden="true"></div>
            <div>
              <span className="stat-label">Done</span>
              <span className="stat-number" id="stat-done-count">
                {insights.done}
              </span>
            </div>
          </div>

          <div className="stat-box stat-postponed">
            <div className="stat-indicator indicator-postponed" aria-hidden="true"></div>
            <div>
              <span className="stat-label">Postponed</span>
              <span className="stat-number" id="stat-postponed-count">
                {insights.postponed}
              </span>
            </div>
          </div>

          <div className="stat-box stat-skipped">
            <div className="stat-indicator indicator-skipped" aria-hidden="true"></div>
            <div>
              <span className="stat-label">Skipped</span>
              <span className="stat-number" id="stat-skipped-count">
                {insights.skipped}
              </span>
            </div>
          </div>

          {insights.unreported > 0 && (
            <div className="stat-box stat-unreported">
              <span className="stat-label">Unreported</span>
              <span className="stat-number" id="stat-unreported-count">
                {insights.unreported}
              </span>
            </div>
          )}

          {insights.avg_start_delay_min !== null &&
            insights.avg_start_delay_min !== undefined && (
              <div className="stat-box stat-delay">
                <span className="stat-label">Avg. Start Delay</span>
                <span className="stat-number" id="stat-delay-count">
                  {insights.avg_start_delay_min} <small>min</small>
                </span>
              </div>
            )}
        </div>
      </div>

      {insights.narrative && (
        <div className="metric-narrative" id="metric-narrative-box">
          <span className="narrative-icon" aria-hidden="true">
            💡
          </span>
          <p className="narrative-text">{insights.narrative}</p>
        </div>
      )}
    </section>
  );
};

export default AdherenceMetricCard;
