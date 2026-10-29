import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const plansApi = fs.readFileSync(new URL('../src/api/plans.ts', import.meta.url), 'utf8');
const planPage = fs.readFileSync(new URL('../src/pages/PlanList.tsx', import.meta.url), 'utf8');
const insightsPage = fs.readFileSync(new URL('../src/pages/Insights.tsx', import.meta.url), 'utf8');
const coachPage = fs.readFileSync(new URL('../src/pages/PersonalAICoach.tsx', import.meta.url), 'utf8');
const coachView = fs.readFileSync(new URL('../src/components/coach/CoachView.tsx', import.meta.url), 'utf8');
const coachActions = fs.readFileSync(new URL('../src/components/coach/coachActions.ts', import.meta.url), 'utf8');
const insightsApi = fs.readFileSync(new URL('../src/api/insights.ts', import.meta.url), 'utf8');

describe('recommendation state regression coverage', () => {
  it('bounds stalled recommendation requests and normalizes null suggestions', () => {
    assert.match(plansApi, /setTimeout\(\(\) => controller\.abort\(\), 10_000\)/);
    assert.match(plansApi, /signal: controller\.signal/);
    assert.match(plansApi, /result\.suggestion \?\? null/);
    assert.match(plansApi, /pendingSuggestions\.get\(planId\)/);
    assert.match(insightsApi, /setTimeout\(\(\) => controller\.abort\(\), 10_000\)/);
  });

  it('renders loading, retryable error, and insufficient-history states', () => {
    assert.match(planPage, /Loading your personalized recommendation/);
    assert.match(planPage, /Recommendation could not be loaded/);
    assert.match(planPage, /No plan-specific suggestion is available right now/);
    assert.match(planPage, /error \? 'Retry'/);
  });

  it('keeps coach recommendations out of Insights and in the dedicated Coach page', () => {
    assert.doesNotMatch(insightsPage, /Personal AI Coach|coach-|submitRecommendationFeedback|Show another idea/);
    assert.match(coachPage, /fetchInsights\('week'\)/);
    assert.match(coachPage, /data\.recommendations \?\? \[\]/);
    assert.match(coachView, /visibleCards\(state\.cards\)/);
    assert.match(coachView, /Evidence/);
    assert.match(coachView, /No ideas are available right now\. Refresh to try again\./);
    assert.match(coachView, /Show another idea/);
  });

  it('allows actionable coach cards to be scheduled and added to plans after confirmation', () => {
    assert.match(coachView, /Add to My Plans/);
    assert.match(coachActions, /deps\.confirm\(`Add/);
    assert.match(coachView, /card\.label && /);
    assert.match(coachView, /coach-narrative-card|coach-history-summary/);
  });

  it('loads plan-specific suggestions only on request and confirms time changes before PUT', () => {
    const start = planPage.indexOf('function SuggestionCard');
    const end = planPage.indexOf('\nexport function PlanList', start);
    const card = planPage.slice(start, end);
    assert.match(card, /await fetchPlanSuggestion\(plan\.id\)/);
    assert.doesNotMatch(card, /useEffect\(/);
    assert.match(card, /onClick=\{\(\) => void loadSuggestion\(\)\}/);
    assert.match(card, /window\.confirm\(`Move/);
    assert.match(card, /await updatePlan\(plan\.id/);
    assert.match(planPage, /deletePlan\(/);
    assert.match(planPage, /handleOutcomeReported/);
  });
});
