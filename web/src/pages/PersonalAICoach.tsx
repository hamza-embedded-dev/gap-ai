import React, { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';
import { fetchInsights, submitRecommendationFeedback } from '../api/insights';
import type { RecommendationCard } from '../api/insights';
import { ApiError } from '../api/client';
import { createPlan } from '../api/plans';
import { generateIdempotencyKey } from '../utils/idempotency';
import { CoachView } from '../components/coach/CoachView';
import type { CoachViewHandlers } from '../components/coach/CoachView';
import {
  addToPlans,
  coachReducer,
  dismissCard,
  effectiveDate,
  effectiveDuration,
  effectiveTime,
  initialCoachState,
  rateCard,
  saveDuration,
} from '../components/coach/coachActions';
import type { CoachDeps } from '../components/coach/coachActions';
import './PersonalAICoach.css';

interface PersonalAICoachProps {
  token: string | null;
  onRequireAuth: () => void;
}

const DEPS: CoachDeps = {
  submitFeedback: submitRecommendationFeedback,
  createPlan,
  confirm: (message) => window.confirm(message),
  newKey: generateIdempotencyKey,
};

export const PersonalAICoach: React.FC<PersonalAICoachProps> = ({ token, onRequireAuth }) => {
  const [state, dispatch] = useReducer(coachReducer, initialCoachState);
  const planKeys = useRef(new Map<string, string>());
  const stateRef = useRef(state);
  stateRef.current = state;
  const [reloadTick, bumpReload] = useReducer((n: number) => n + 1, 0);

  // Recommendations come from the existing GET /insights response (user-scoped by the bearer token).
  useEffect(() => {
    let cancelled = false;
    if (!token) return; // The signed-out state is derived below.
    dispatch({ type: 'load_start' });
    fetchInsights('week')
      .then((data) => {
        if (!cancelled) {
          dispatch({ type: 'load_ok', cards: data.recommendations ?? [], insights: data });
        }
      })
      .catch((err: unknown) => {
        // A 401 clears the token (which cancels this effect); still surface it.
        if (cancelled && !(err instanceof ApiError && err.status === 401)) return;
        if (err instanceof ApiError) {
          if (err.errorType === 'aborted') return;
          dispatch({ type: 'load_fail', error: { message: err.message, statusCode: err.status, errorType: err.errorType } });
        } else {
          dispatch({ type: 'load_fail', error: { message: err instanceof Error ? err.message : 'An unexpected error occurred while loading ideas.' } });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, reloadTick]);

  const run = useCallback(async (id: string, action: () => Promise<string | null>, onSuccess?: () => void) => {
    if (stateRef.current.busyId) return;
    dispatch({ type: 'action_start', id });
    try {
      const notice = await action();
      onSuccess?.();
      dispatch({ type: 'action_ok', notice });
    } catch (e) {
      dispatch({ type: 'action_fail', message: e instanceof Error ? e.message : 'Action failed. Try again.' });
    }
  }, []);

  const handlers: CoachViewHandlers = useMemo(() => ({
    onRefresh: () => bumpReload(),
    onShowAnother: () => dispatch({ type: 'rotate' }),
    onRate: (card: RecommendationCard, rating) =>
      void run(card.id, () => rateCard(DEPS, card, rating), () => dispatch({ type: 'rated', id: card.id, rating })),
    onDismiss: (card) =>
      void run(card.id, () => dismissCard(DEPS, card), () => dispatch({ type: 'dismissed', id: card.id })),
    onToggleWhy: (card) => dispatch({ type: 'toggle_why', id: card.id }),
    onDurationInput: (card, minutes) => dispatch({ type: 'set_duration', id: card.id, minutes }),
    onDateInput: (card, date) => dispatch({ type: 'set_date', id: card.id, date }),
    onTimeInput: (card, time) => dispatch({ type: 'set_time', id: card.id, time }),
    onSaveDuration: (card) =>
      void run(card.id, () => saveDuration(DEPS, card, effectiveDuration(card, stateRef.current.durations))),
    onAddToPlans: (card) => {
      const minutes = effectiveDuration(card, stateRef.current.durations);
      const scheduledDate = effectiveDate(card, stateRef.current.scheduledDates);
      const scheduledTime = effectiveTime(card, stateRef.current.scheduledTimes);
      return void run(card.id, () =>
        addToPlans(DEPS, card, minutes, planKeys.current, {
          date: scheduledDate,
          time: scheduledTime,
        })
      );
    },
    onRequireAuth,
  }), [run, onRequireAuth]);

  const viewState = token
    ? state
    : { ...state, status: 'error' as const, cards: [], error: { message: 'Sign in to see your personal ideas.', errorType: 'auth_required' } };

  return <CoachView state={viewState} handlers={handlers} />;
};
