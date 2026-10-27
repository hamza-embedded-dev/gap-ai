import React, { useCallback, useEffect, useRef, useState } from 'react';
import { fetchInsights, submitRecommendationFeedback } from '../api/insights';
import type { InsightsPeriod, InsightsResponse } from '../api/insights';
import { ApiError } from '../api/client';
import { AdherenceMetricCard } from '../components/insights/AdherenceMetricCard';
import { DistributionCharts } from '../components/insights/DistributionCharts';
import { PostponedTargetsList } from '../components/insights/PostponedTargetsList';
import { EmptyInsights } from '../components/insights/EmptyInsights';
import { SampleDataBadge } from '../components/insights/SampleDataBadge';
import { InsightsSkeleton } from '../components/insights/InsightsSkeleton';
import { ErrorState } from '../components/ui/ErrorState';
import { createPlan } from '../api/plans';
import { generateIdempotencyKey } from '../utils/idempotency';
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

interface InsightsProps {
  token: string | null;
  onRequireAuth: () => void;
}

export const Insights: React.FC<InsightsProps> = ({ token, onRequireAuth }) => {
  const [period, setPeriod] = useState<InsightsPeriod>('week');
  const [insights, setInsights] = useState<InsightsResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRetrying, setIsRetrying] = useState<boolean>(false);
  const [errorData, setErrorData] = useState<ErrorStateData | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [ratings, setRatings] = useState<Record<string, 'useful' | 'not_useful'>>({});
  const [durations, setDurations] = useState<Record<string, number>>({});
  const [whyOpen, setWhyOpen] = useState<Record<string, boolean>>({});
  const recommendationPlanKeys = useRef(new Map<string, string>());

  const runCardAction = async (id: string, action: () => Promise<void>) => {
    if (actionBusy) return;
    setActionBusy(id); setActionError(null); setActionNotice(null);
    try { await action(); } catch (e) { setActionError(e instanceof Error ? e.message : 'Action failed. Try again.'); }
    finally { setActionBusy(null); }
  };

  const loadData = useCallback(async (selectedPeriod: InsightsPeriod, isManualRetry = false) => {
    if (!token) {
      setInsights(null);
      setErrorData({
        message: 'Sign in to load your insights and plan activity.',
        errorType: 'auth_required',
      });
      setIsLoading(false);
      setIsRetrying(false);
      return;
    }

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
  }, [token]);

  useEffect(() => {
    let isCancelled = false;

    const run = async () => {
      if (!token) {
        setInsights(null);
        setErrorData((current) => current?.statusCode === 401 ? current : {
          message: 'Sign in to load your insights and plan activity.',
          errorType: 'auth_required',
        });
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      setErrorData(null);
      try {
        const data = await fetchInsights(period);
        if (!isCancelled) {
          setInsights(data);
        }
      } catch (err) {
        // A 401 clears the token and changes the effect dependencies, which
        // cancels this request. Preserve its actual error so the user sees
        // the authorization failure instead of a generic missing-session state.
        if (!isCancelled || (err instanceof ApiError && err.status === 401)) {
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
  }, [period, token]);

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
          onRequireAuth={onRequireAuth}
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
      {!isLoading && !errorData && insights && (
        <section className="coach-section" aria-label="Your Personal AI Coach">
          <h2>Your Personal AI Coach</h2>
          {(insights.recommendations ?? []).length === 0 ? (
            <p>No ideas are available right now. Refresh to try again.</p>
          ) : (
            <div className="coach-grid">{(insights.recommendations ?? []).slice(0, 3).map((item) => (
              <article className="coach-card" key={item.id}>
                {item.label && <small>{item.label}</small>}
                <h3>{item.title}</h3><p>{item.message}</p><p>{item.why}</p>
                {(item.source === 'behavior' || item.source === 'contextual') && <><small>Evidence: {Object.entries(item.evidence).map(([key, value]) => `${key}: ${value}`).join(' · ')}</small><small>Confidence: {item.confidence}</small></>}
                <p><strong>Next step:</strong> {item.next_step}</p>
                {whyOpen[item.id] && <p role="status">{item.why}{item.source === 'discovery' ? ' This is a neutral starter and uses no history.' : ''}</p>}
                {item.source === 'discovery' && <label>Duration (minutes) <input type="number" min={5} max={1440} value={durations[item.id] ?? item.duration_minutes ?? 20} onChange={e => setDurations(v => ({...v, [item.id]: Math.max(5, Math.min(1440, Number(e.target.value) || 5))}))} /></label>}
                <div className="coach-actions">
                  <button type="button" disabled={actionBusy !== null} onClick={() => { setWhyOpen(v => ({...v, [item.id]: !v[item.id]})); }}>Tell me why this was suggested</button>
                  <button type="button" disabled={actionBusy !== null} onClick={() => void runCardAction(item.id, async () => { await submitRecommendationFeedback({recommendation_id:item.id, action:'dismissed'}); setInsights(v => v ? {...v, recommendations:(v.recommendations ?? []).filter(r => r.id !== item.id)} : v); })}>Not interested</button>
                  <button type="button" aria-pressed={ratings[item.id] === 'useful'} disabled={actionBusy !== null} onClick={() => void runCardAction(item.id, async () => { await submitRecommendationFeedback({recommendation_id:item.id, action:'accepted', rating:'useful'}); setRatings(v => ({...v, [item.id]:'useful'})); setActionNotice('Thanks! Marked as useful. We will prioritize similar ideas.'); })}>{ratings[item.id] === 'useful' ? 'Useful ✓' : 'Useful'}</button>
                  <button type="button" aria-pressed={ratings[item.id] === 'not_useful'} disabled={actionBusy !== null} onClick={() => void runCardAction(item.id, async () => { await submitRecommendationFeedback({recommendation_id:item.id, action:'accepted', rating:'not_useful'}); setRatings(v => ({...v, [item.id]:'not_useful'})); setActionNotice('Thanks! Marked as not useful. We will show fewer ideas like this.'); })}>{ratings[item.id] === 'not_useful' ? 'Not useful ✓' : 'Not useful'}</button>
                  {item.source === 'discovery' && <button type="button" disabled={actionBusy !== null} onClick={() => void runCardAction(item.id, async () => { await submitRecommendationFeedback({recommendation_id:item.id, action:'modified', payload:{duration_minutes:durations[item.id] ?? item.duration_minutes}}); })}>Change duration</button>}
                  {item.source === 'discovery' && <button type="button" disabled={actionBusy !== null} onClick={() => void runCardAction(item.id, async () => {
                    const duration = durations[item.id] ?? item.duration_minutes ?? 20;
                    const now = new Date(); const date = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
                    const time = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;
                    if (!window.confirm(`Add “${item.title}” to My Plans for today at ${time} (${duration} minutes)?`)) return;
                    let key = recommendationPlanKeys.current.get(item.id);
                    if (!key) { key = generateIdempotencyKey(); recommendationPlanKeys.current.set(item.id, key); }
                    await createPlan({intent:'create_plan', title:item.title, category:'personal', date, time, duration_minutes:duration, recurrence:null, language:'en', needs_weather_check:false, clarification_question:null, confidence:1}, key);
                    await submitRecommendationFeedback({recommendation_id:item.id, action:'accepted'});
                  })}>{actionBusy === item.id ? 'Working…' : 'Add to My Plans'}</button>}
                </div>
              </article>
            ))}</div>
          )}
          <button type="button" onClick={() => setInsights(v => v?.recommendations?.length ? {...v, recommendations:[...v.recommendations.slice(1), v.recommendations[0]]} : v)} disabled={isRetrying || actionBusy !== null}>
            {isRetrying ? 'Loading another idea…' : 'Show another idea'}
          </button>
          {actionNotice && <p role="status">{actionNotice}</p>}
          {actionError && <p role="alert">{actionError}</p>}
        </section>
      )}
    </div>
  );
};

export default Insights;
