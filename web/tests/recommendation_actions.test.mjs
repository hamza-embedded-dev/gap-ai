import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

describe('Insights recommendation card actions', () => {
  const source = readFileSync(new URL('../src/pages/Insights.tsx', import.meta.url), 'utf8');
  it('exposes requested actions, confirmation, busy lock, and error state', () => {
    for (const text of ['Show another idea', 'Not interested', 'Tell me why this was suggested', 'Change duration', 'Add to My Plans']) assert.ok(source.includes(text));
    assert.ok(source.includes('window.confirm('));
    assert.ok(source.includes('actionBusy !== null'));
    assert.ok(source.includes('role="alert"'));
    assert.ok(source.includes('createPlan('));
    assert.ok(source.includes('generateIdempotencyKey()'));
  });

  it('Useful sends contract-valid feedback and shows visible success state', () => {
    const useful = source.split('\n').find((l) => l.includes("rating:'useful'"));
    assert.ok(useful, 'Useful handler exists');
    assert.ok(useful.includes("action:'accepted'"));
    assert.ok(useful.includes('recommendation_id:item.id'));
    assert.ok(useful.includes('await submitRecommendationFeedback'));
    // Success must update UI after the awaited request, not before.
    assert.ok(useful.indexOf('setRatings') > useful.indexOf('await submitRecommendationFeedback'));
    assert.ok(useful.includes('setActionNotice('));
    assert.ok(source.includes('role="status">{actionNotice}'));
    assert.ok(source.includes("aria-pressed={ratings[item.id] === 'useful'}"));
  });
});
