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
});
