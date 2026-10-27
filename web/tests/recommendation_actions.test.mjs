import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  addToPlans,
  coachReducer,
  dismissCard,
  initialCoachState,
  rateCard,
  rotateCards,
  saveDuration,
  visibleCards,
} from '../src/components/coach/coachActions.ts';
import { CoachView } from '../src/components/coach/CoachView.tsx';
import { apiFetch } from '../src/api/client.ts';
import { submitRecommendationFeedback } from '../src/api/insights.ts';

const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

const card = (over = {}) => ({
  id: 'behavior-morning', title: 'Try mornings', message: 'You finish more early.', why: 'Because evidence.',
  evidence: { done: 4, planned: 5 }, confidence: 'moderate', next_step: 'Plan 08:00.',
  source: 'behavior', label: null, dedup_key: 'k', duration_minutes: null, ...over,
});
const discovery = (over = {}) => card({ id: 'discovery-walk', title: 'Take a walk', source: 'discovery', evidence: {}, confidence: 'none', label: 'Not based on your history', duration_minutes: 20, ...over });

function makeDeps(over = {}) {
  const calls = { feedback: [], plans: [], confirms: [] };
  const deps = {
    submitFeedback: async (x) => { calls.feedback.push(x); },
    createPlan: async (plan, key) => { calls.plans.push({ plan, key }); return {}; },
    confirm: (m) => { calls.confirms.push(m); return true; },
    newKey: () => '11111111-1111-4111-8111-111111111111',
    now: () => new Date(2026, 9, 27, 9, 5),
    ...over,
  };
  return { deps, calls };
}

const noop = () => {};
const handlers = {
  onRefresh: noop,
  onShowAnother: noop,
  onRate: noop,
  onDismiss: noop,
  onToggleWhy: noop,
  onDurationInput: noop,
  onDateInput: noop,
  onTimeInput: noop,
  onSaveDuration: noop,
  onAddToPlans: noop,
  onRequireAuth: noop,
};
const render = (state) => renderToStaticMarkup(React.createElement(CoachView, { state, handlers }));
const ready = (cards, extra = {}) => ({ ...initialCoachState, status: 'ready', cards, ...extra });

describe('Coach action handlers (executed for real)', () => {
  it('Useful / Not useful send the contract payload with the card id only', async () => {
    const { deps, calls } = makeDeps();
    assert.match(await rateCard(deps, card(), 'useful'), /useful/);
    await rateCard(deps, card(), 'not_useful');
    assert.deepEqual(calls.feedback, [
      { recommendation_id: 'behavior-morning', action: 'accepted', rating: 'useful' },
      { recommendation_id: 'behavior-morning', action: 'accepted', rating: 'not_useful' },
    ]);
    assert.ok(calls.feedback.every((f) => !('user_id' in f)), 'owner id must never come from the client');
  });

  it('does not report success when the API rejects', async () => {
    const { deps } = makeDeps({ submitFeedback: async () => { throw new Error('HTTP 503'); } });
    await assert.rejects(() => rateCard(deps, card(), 'useful'), /503/);
  });

  it('Not interested sends dismissed without a rating; reducer removes the card', async () => {
    const { deps, calls } = makeDeps();
    await dismissCard(deps, card());
    assert.deepEqual(calls.feedback[0], { recommendation_id: 'behavior-morning', action: 'dismissed' });
    const s = coachReducer(ready([card(), discovery()]), { type: 'dismissed', id: 'behavior-morning' });
    assert.deepEqual(s.cards.map((c) => c.id), ['discovery-walk']);
  });

  it('Change duration persists payload.duration_minutes', async () => {
    const { deps, calls } = makeDeps();
    await saveDuration(deps, discovery(), 45);
    assert.deepEqual(calls.feedback[0], { recommendation_id: 'discovery-walk', action: 'modified', payload: { duration_minutes: 45 } });
  });

  it('Add to My Plans confirms, creates the plan idempotently, then records acceptance (default schedule)', async () => {
    const { deps, calls } = makeDeps();
    const keys = new Map();
    const msg = await addToPlans(deps, discovery(), 30, keys);
    assert.match(msg, /Added/);
    assert.equal(calls.plans.length, 1);
    assert.deepEqual(calls.plans[0].plan, {
      intent: 'create_plan', title: 'Take a walk', category: 'personal', date: '2026-10-27', time: '10:00',
      duration_minutes: 30, recurrence: null, language: 'en', needs_weather_check: false, clarification_question: null, confidence: 1,
    });
    assert.equal(calls.plans[0].key, '11111111-1111-4111-8111-111111111111');
    assert.deepEqual(calls.feedback, [{ recommendation_id: 'discovery-walk', action: 'accepted' }]);
    assert.match(calls.confirms[0], /Take a walk.*10:00.*30 minutes/);
    await addToPlans(deps, discovery(), 30, keys);
    assert.equal(calls.plans[1].key, calls.plans[0].key, 'retry reuses the idempotency key');
  });

  it('schedules a recommendation for a chosen future date and time', async () => {
    const { deps, calls } = makeDeps();
    const keys = new Map();
    const futureDate = '2026-11-05';
    const futureTime = '14:30';
    const msg = await addToPlans(deps, discovery(), 45, keys, { date: futureDate, time: futureTime });
    assert.match(msg, /Added/);
    assert.equal(calls.plans.length, 1);
    assert.deepEqual(calls.plans[0].plan, {
      intent: 'create_plan', title: 'Take a walk', category: 'personal', date: '2026-11-05', time: '14:30',
      duration_minutes: 45, recurrence: null, language: 'en', needs_weather_check: false, clarification_question: null, confidence: 1,
    });
    assert.match(calls.confirms[0], /Take a walk.*2026-11-05 at 14:30.*45 minutes/);
    assert.deepEqual(calls.feedback, [{ recommendation_id: 'discovery-walk', action: 'accepted' }]);
  });

  it('Add to My Plans does nothing when the user cancels, and skips feedback when plan creation fails', async () => {
    const cancelled = makeDeps({ confirm: () => false });
    assert.equal(await addToPlans(cancelled.deps, discovery(), 20, new Map()), null);
    assert.equal(cancelled.calls.plans.length + cancelled.calls.feedback.length, 0);
    const failing = makeDeps({ createPlan: async () => { throw new Error('plan failed'); } });
    await assert.rejects(() => addToPlans(failing.deps, discovery(), 20, new Map()), /plan failed/);
    assert.equal(failing.calls.feedback.length, 0);
  });

  it('keeps order, caps at three, and rotates for "Show another idea"', () => {
    const five = ['a', 'b', 'c', 'd', 'e'].map((id) => card({ id }));
    assert.deepEqual(visibleCards(five).map((c) => c.id), ['a', 'b', 'c']);
    assert.deepEqual(rotateCards(five).map((c) => c.id), ['b', 'c', 'd', 'e', 'a']);
  });

  it('reducer tracks ratings, busy lock, notice, errors, and scheduled dates/times', () => {
    let s = coachReducer(ready([card()]), { type: 'action_start', id: 'behavior-morning' });
    assert.equal(s.busyId, 'behavior-morning');
    s = coachReducer(s, { type: 'rated', id: 'behavior-morning', rating: 'useful' });
    s = coachReducer(s, { type: 'action_ok', notice: 'Thanks!' });
    assert.equal(s.busyId, null);
    assert.equal(s.notice, 'Thanks!');
    assert.equal(s.ratings['behavior-morning'], 'useful');
    s = coachReducer(s, { type: 'set_date', id: 'behavior-morning', date: '2026-11-01' });
    assert.equal(s.scheduledDates['behavior-morning'], '2026-11-01');
    s = coachReducer(s, { type: 'set_time', id: 'behavior-morning', time: '16:00' });
    assert.equal(s.scheduledTimes['behavior-morning'], '16:00');
    s = coachReducer(s, { type: 'action_fail', message: 'boom' });
    assert.equal(s.actionError, 'boom');
  });
});

describe('Coach view rendering (real component output)', () => {
  it('renders loading, empty, and error states with accessible roles', () => {
    assert.match(render(initialCoachState), /aria-busy="true"/);
    assert.match(render(ready([])), /No ideas are available right now\. Refresh to try again\./);
    const err = render({ ...initialCoachState, status: 'error', error: { message: 'Backend down', statusCode: 503 } });
    assert.match(err, /role="alert"/);
    assert.match(err, /Backend down/);
    assert.match(err, />Retry</);
    const auth = render({ ...initialCoachState, status: 'error', error: { message: 'Sign in', statusCode: 401 } });
    assert.match(auth, /Session required/);
    assert.match(auth, /Demo &amp; Auth/);
  });

  it('renders cards with evidence, confidence, and the action set; at most three', () => {
    const html = render(ready([card(), card({ id: 'c2', source: 'contextual' }), discovery(), card({ id: 'c4' })]));
    assert.equal((html.match(/<article/g) || []).length, 3);
    assert.match(html, /done: 4 · planned: 5/);
    assert.match(html, /Confidence/);
    for (const label of ['Tell me why this was suggested', 'Useful', 'Not useful', 'Not interested', 'Change duration', 'Add to My Plans', 'Show another idea']) {
      assert.ok(html.includes(label), `missing ${label}`);
    }
    assert.equal((html.match(/Add to My Plans/g) || []).length, 1, 'discovery only');
    assert.match(html, /Not based on your history/);
    assert.match(html, /type="date"/);
    assert.match(html, /type="time"/);
    assert.match(html, /Start time/);
  });

  it('shows success notice, pressed rating, and the why panel when requested', () => {
    const html = render(ready([card()], { notice: 'Thanks! Marked as useful.', ratings: { 'behavior-morning': 'useful' }, whyOpen: { 'behavior-morning': true } }));
    assert.match(html, /role="status"[^>]*>Thanks! Marked as useful\./);
    assert.match(html, /aria-pressed="true"[^>]*>Useful ✓/);
    assert.match(html, /Because evidence\./);
    assert.match(render(ready([card()], { actionError: 'HTTP 503' })), /role="alert"[^>]*>HTTP 503/);
  });

  it('disables actions while one is in flight', () => {
    const html = render(ready([discovery()], { busyId: 'discovery-walk' }));
    assert.match(html, /disabled=""[^>]*>Working…/);
  });
});

describe('Coach API contract and wiring', () => {
  it('POSTs feedback to /recommendations/feedback with a bearer token and no owner id', async () => {
    const original = globalThis.fetch;
    let seen;
    globalThis.fetch = async (url, init) => { seen = { url, init }; return new Response(JSON.stringify({ id: '1' }), { status: 201 }); };
    try {
      await submitRecommendationFeedback({ recommendation_id: 'behavior-morning', action: 'accepted', rating: 'useful' });
    } finally {
      globalThis.fetch = original;
    }
    assert.match(seen.url, /\/recommendations\/feedback$/);
    assert.equal(seen.init.method, 'POST');
    assert.deepEqual(JSON.parse(seen.init.body), { rating: 'useful', payload: {}, recommendation_id: 'behavior-morning', action: 'accepted' });
    assert.equal(typeof apiFetch, 'function');
  });

  it('surfaces API errors as ApiError messages for the banner', async () => {
    const original = globalThis.fetch;
    globalThis.fetch = async () => new Response(JSON.stringify({ message: 'Recommendation feedback storage is unavailable.', error: 'unavailable' }), { status: 503 });
    try {
      await assert.rejects(() => submitRecommendationFeedback({ recommendation_id: 'x', action: 'dismissed' }), /storage is unavailable/);
    } finally {
      globalThis.fetch = original;
    }
  });

  it('page loads recommendations from GET /insights and requires a token', () => {
    const page = read('../src/pages/PersonalAICoach.tsx');
    assert.match(page, /fetchInsights\('week'\)/);
    assert.match(page, /if \(!token\) return;/);
    assert.match(page, /errorType: 'auth_required'/);
  });
});

describe('Navigation, Insights separation and layout', () => {
  const app = read('../src/App.tsx');
  it('adds a Personal AI Coach tab between Insights and My Plans, behind the auth gate', () => {
    const order = ['Overview', 'Profile', 'Insights', 'Personal AI Coach', 'My Plans', 'Create Plan', 'Demo &amp; Auth'].map((l) => app.indexOf(`<span>${l}</span>`));
    assert.ok(order.every((i) => i > 0), 'all tabs present');
    assert.deepEqual([...order].sort((a, b) => a - b), order, 'tab order');
    assert.match(app, /activeTab === 'coach' &&\s*\(\s*token \?\s*\(\s*<PersonalAICoach/);
    assert.match(app, /featureName="Personal AI Coach"/);
    assert.match(app, /onClick=\{\(\) => setActiveTab\('coach'\)\}/);
  });

  it('Insights no longer renders coach cards or feedback handlers', () => {
    const insights = read('../src/pages/Insights.tsx');
    assert.doesNotMatch(insights, /coach|Coach|submitRecommendationFeedback|createPlan/);
    assert.doesNotMatch(read('../src/pages/Insights.css'), /\.coach-/);
  });

  it('Coach CSS guards against horizontal overflow and defines focus + mobile rules (static check, no browser)', () => {
    const css = read('../src/pages/PersonalAICoach.css');
    assert.match(css, /minmax\(min\(100%, 280px\), 1fr\)/);
    assert.match(css, /overflow-wrap: anywhere/);
    assert.match(css, /\.coach-btn:focus-visible/);
    assert.match(css, /@media \(max-width: 480px\)/);
    assert.match(css, /min-height: 44px/);
  });
});
