import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const plansApi = fs.readFileSync(new URL('../src/api/plans.ts', import.meta.url), 'utf8');
const planPage = fs.readFileSync(new URL('../src/pages/PlanList.tsx', import.meta.url), 'utf8');
const insightsPage = fs.readFileSync(new URL('../src/pages/Insights.tsx', import.meta.url), 'utf8');
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

  it('renders at most three evidence-backed coach recommendations with empty and retry states', () => {
    assert.match(insightsPage, /Your Personal AI Coach/);
    assert.match(insightsPage, /\(insights\.recommendations \?\? \[\]\)\.slice\(0, 3\)/);
    assert.match(insightsPage, /Evidence:/);
    assert.match(insightsPage, /No ideas are available right now\. Refresh to try again\./);
    assert.match(insightsPage, /retryText="Retry Connection"/);
    assert.match(insightsPage, /Show another idea/);
  });

  it('renders contextual basis and keeps coach-card plan creation limited to confirmed discovery ideas', () => {
    assert.match(insightsPage, /item\.label && <small>\{item\.label\}<\/small>/);
    assert.match(insightsPage, /item\.source === 'contextual'/);
    assert.match(insightsPage, /item\.source === 'discovery' && <button/);
    assert.match(insightsPage, /window\.confirm\(`Add/);
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
