import React, { useCallback, useEffect, useState } from 'react';
import { fetchInsights } from '../api/insights';
import type { InsightsPeriod, InsightsResponse } from '../api/insights';
import { ApiError } from '../api/client';
import { AdherenceMetricCard } from '../components/insights/AdherenceMetricCard';
import { DistributionCharts } from '../components/insights/DistributionCharts';
import { PostponedTargetsList } from '../components/insights/PostponedTargetsList';
import { EmptyInsights } from '../components/insights/EmptyInsights';
import { SampleDataBadge } from '../components/insights/SampleDataBadge';
import { InsightsSkeleton } from '../components/insights/InsightsSkeleton';
import { ErrorState } from '../components/ui/ErrorState';
import './Insights.css';

const PERIOD_LABELS: Record<InsightsPeriod, string> = {
  week: 'Week',
  last_week: 'Last Week',
  all: 'All Time',
};

interface ErrorStateData {
  message: string;
  statusCode?: number;
  errorType?: string;
}

export const Insights: React.FC = () => {
  const [period, setPeriod] = useState<InsightsPeriod>('week');
  const [insights, setInsights] = useState<InsightsResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRetrying, setIsRetrying] = useState<boolean>(false);
  const [errorData, setErrorData] = useState<ErrorStateData | null>(null);

  const loadData = useCallback(async (selectedPeriod: InsightsPeriod, isManualRetry = false) => {
    if (isManualRetry) {
      setIsRetrying(true);
    } else {
      setIsLoading(true);
    }
    setErrorData(null);

    try {
      const data = await fetchInsights(selectedPeriod);
      setInsights(data);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorData({
          message: err.message,
          statusCode: err.status,
          errorType: err.errorType,
        });
      } else {
        const msg =
          err instanceof Error
            ? err.message
            : 'An unexpected error occurred while fetching insights data.';
        setErrorData({ message: msg });
      }
      setInsights(null);
    } finally {
      setIsLoading(false);
      setIsRetrying(false);
    }
  }, []);

  useEffect(() => {
    let isCancelled = false;

    const run = async () => {
      setIsLoading(true);
      setErrorData(null);
      try {
        const data = await fetchInsights(period);
        if (!isCancelled) {
          setInsights(data);
        }
      } catch (err) {
        if (!isCancelled) {
          if (err instanceof ApiError) {
            setErrorData({
              message: err.message,
              statusCode: err.status,
              errorType: err.errorType,
            });
          } else {
            const msg =
              err instanceof Error
                ? err.message
                : 'An unexpected error occurred while fetching insights data.';
            setErrorData({ message: msg });
          }
          setInsights(null);
        }
      } finally {
        if (!isCancelled) {
          setIsLoading(false);
        }
      }
    };

    void run();

    return () => {
      isCancelled = true;
    };
  }, [period]);

  const handlePeriodChange = (newPeriod: InsightsPeriod) => {
    if (newPeriod !== period) {
      setPeriod(newPeriod);
    }
  };

  const isDemo =
    insights?.data_label === 'demo' ||
    insights?.is_demo === true;

  // Empty state check per API contract:
  // If there are no eligible plans, adherence_pct is null or planned is 0
  const hasEnoughData =
    insights !== null &&
    insights.planned > 0 &&
    insights.adherence_pct !== null &&
    insights.adherence_pct !== undefined;

  return (
    <div className="insights-page" id="insights-dashboard">
      {/* Top Header and Period Filter Bar */}
      <header className="insights-top-bar">
        <div className="insights-heading-group">
          <div className="insights-title-row">
            <h1 className="insights-main-title">Behavior &amp; Adherence Insights</h1>
            {isDemo && <SampleDataBadge />}
          </div>
          <p className="insights-subtitle">
            Track plan adherence, postponement habits, and time distribution across activities.
          </p>
        </div>

        {/* Period Selector */}
        <div
          className="period-selector-wrapper"
          role="group"
          aria-label="Insights Period Selection"
          id="period-selector"
        >
          {(['week', 'last_week', 'all'] as InsightsPeriod[]).map((p) => (
            <button
              key={p}
              id={`period-btn-${p}`}
              type="button"
              className={`period-btn ${period === p ? 'active' : ''}`}
              onClick={() => handlePeriodChange(p)}
              disabled={isLoading || isRetrying}
              aria-pressed={period === p}
            >
              {PERIOD_LABELS[p]}
            </button>
          ))}
        </div>
      </header>

      {/* 1. Loading State: Rich Skeleton UI */}
      {isLoading && (
        <InsightsSkeleton periodLabel={PERIOD_LABELS[period]} />
      )}

      {/* 2. Error State: Network and Server Failure Protection */}
      {!isLoading && errorData && (
        <ErrorState
          id="insights-error"
          message={errorData.message}
          statusCode={errorData.statusCode}
          errorType={errorData.errorType}
          onRetry={() => loadData(period, true)}
          isRetrying={isRetrying}
          retryText="Retry Connection"
        />
      )}

      {/* 3. Empty State: "Not enough data" Condition */}
      {!isLoading && !errorData && !hasEnoughData && (
        <EmptyInsights
          periodLabel={PERIOD_LABELS[period]}
          onRefresh={() => loadData(period, true)}
        />
      )}

      {/* 4. Active Analytics Visualizations */}
      {!isLoading && !errorData && hasEnoughData && insights && (
        <>
          {/* Adherence Percentage & Counters */}
          <AdherenceMetricCard insights={insights} />

          {/* Weekday and Hour Distribution Charts */}
          <DistributionCharts
            byWeekday={insights.by_weekday}
            byHour={insights.by_hour}
          />

          {/* Postponed Targets */}
          <PostponedTargetsList targets={insights.postponed_targets} />
        </>
      )}
    </div>
  );
};

export default Insights;
