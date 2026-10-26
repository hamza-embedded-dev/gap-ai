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
    assert.match(planPage, /More completed or reported plans are needed/);
    assert.match(planPage, /setRetry\(\(n\) => n \+ 1\)/);
  });

  it('renders at most three evidence-backed coach recommendations with empty and retry states', () => {
    assert.match(insightsPage, /Your Personal AI Coach/);
    assert.match(insightsPage, /\(insights\.recommendations \?\? \[\]\)\.slice\(0, 3\)/);
    assert.match(insightsPage, /Evidence:/);
    assert.match(insightsPage, /At least 3 reported outcomes are required/);
    assert.match(insightsPage, /Refresh recommendations/);
  });
});
