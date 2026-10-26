import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { nextOnboardingField, recordOnboardingAnswer, recordOnboardingSkip } from '../src/utils/onboarding.ts';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../src');

describe('personalization onboarding', () => {
  it('resumes at first unanswered field and never repeats answered or skipped fields', () => {
    const fields = ['name', 'interests', 'goals'];
    const answered = recordOnboardingAnswer('name', [], []);
    const skipped = recordOnboardingSkip('interests', []);
    assert.equal(nextOnboardingField(fields, answered.onboarding_completed, skipped), 'goals');
  });

  it('allows a skipped field after explicit deletion clears its skip marker', () => {
    const skipped = recordOnboardingSkip('interests', []);
    assert.equal(nextOnboardingField(['interests'], [], skipped), null);
    assert.equal(nextOnboardingField(['interests'], [], skipped.filter(field => field !== 'interests')), 'interests');
  });

  it('contains Turkish and English reset details and structured profile editing controls', () => {
    const page = fs.readFileSync(path.join(root, 'pages/Profile.tsx'), 'utf8');
    for (const text of ['Will be deleted:', 'Will be kept:', 'Silinecek:', 'Korunacak:', 'Confirm reset', 'Sıfırlamayı onayla', 'Delete answer', 'Yanıtı sil']) {
      assert.ok(page.includes(text), `Expected profile UI to include ${text}`);
    }
  });
});
