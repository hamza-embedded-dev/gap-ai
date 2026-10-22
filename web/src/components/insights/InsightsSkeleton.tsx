import React from 'react';
import { Skeleton } from '../ui/Skeleton';
import './InsightsSkeleton.css';

export interface InsightsSkeletonProps {
  periodLabel?: string;
}

export const InsightsSkeleton: React.FC<InsightsSkeletonProps> = ({
  periodLabel = 'selected period',
}) => {
  return (
    <div
      className="insights-skeleton-container"
      id="insights-skeleton"
      role="status"
      aria-busy="true"
      aria-label={`Loading analytics data for ${periodLabel}...`}
    >
      <div className="visually-hidden">Loading insights data for {periodLabel}...</div>

      {/* 1. Adherence Metric Card Skeleton */}
      <section className="skeleton-card metric-skeleton-card">
        <div className="skeleton-header-row">
          <div className="skeleton-heading-group">
            <Skeleton width="120px" height="12px" className="mb-2" />
            <Skeleton width="220px" height="24px" />
          </div>
          <Skeleton width="90px" height="28px" variant="text" />
        </div>

        <div className="metric-skeleton-body">
          {/* Gauge Circle */}
          <div className="gauge-skeleton-wrapper">
            <Skeleton width="108px" height="108px" variant="circular" />
          </div>

          {/* Stats Grid Placeholders */}
          <div className="stats-skeleton-grid">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="stat-skeleton-box">
                <Skeleton width="60%" height="12px" className="mb-2" />
                <Skeleton width="40%" height="22px" />
              </div>
            ))}
          </div>
        </div>

        {/* Narrative Box */}
        <div className="narrative-skeleton-box">
          <Skeleton width="100%" height="16px" className="mb-2" />
          <Skeleton width="80%" height="16px" />
        </div>
      </section>

      {/* 2. Distribution Charts Skeleton */}
      <div className="distribution-skeleton-container">
        {/* Weekday Chart Skeleton */}
        <section className="skeleton-card chart-skeleton-card">
          <div className="skeleton-header-row">
            <div>
              <Skeleton width="100px" height="12px" className="mb-2" />
              <Skeleton width="180px" height="20px" />
            </div>
            <Skeleton width="120px" height="14px" />
          </div>

          <div className="bars-skeleton-vertical-list">
            {[1, 2, 3, 4, 5, 6, 7].map((day) => (
              <div key={day} className="weekday-skeleton-row">
                <Skeleton width="28px" height="12px" />
                <Skeleton width="100%" height="24px" />
              </div>
            ))}
          </div>
        </section>

        {/* Hour Chart Skeleton */}
        <section className="skeleton-card chart-skeleton-card">
          <div className="skeleton-header-row">
            <div>
              <Skeleton width="100px" height="12px" className="mb-2" />
              <Skeleton width="180px" height="20px" />
            </div>
            <Skeleton width="120px" height="14px" />
          </div>

          <div className="hour-skeleton-bars">
            {[40, 75, 55, 90, 60, 80, 45, 70].map((h, idx) => (
              <div key={idx} className="hour-skeleton-col">
                <Skeleton width="100%" height={`${h}%`} />
                <Skeleton width="16px" height="10px" />
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* 3. Postponed Targets Skeleton */}
      <section className="skeleton-card">
        <div className="skeleton-header-row">
          <div>
            <Skeleton width="110px" height="12px" className="mb-2" />
            <Skeleton width="160px" height="20px" />
          </div>
          <Skeleton width="70px" height="22px" />
        </div>

        <div className="targets-skeleton-grid">
          {[1, 2, 3].map((item) => (
            <div key={item} className="target-skeleton-item">
              <div>
                <Skeleton width="80px" height="14px" className="mb-2" />
                <Skeleton width="50px" height="12px" />
              </div>
              <Skeleton width="40px" height="28px" />
            </div>
          ))}
        </div>
      </section>
    </div>
  );
};

export default InsightsSkeleton;
