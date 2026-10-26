import type { OnboardingField } from '../types/profile';

export function nextOnboardingField(fields: OnboardingField[], completed: OnboardingField[] = [], skipped: OnboardingField[] = []): OnboardingField | null {
  return fields.find(field => !completed.includes(field) && !skipped.includes(field)) ?? null;
}

export function recordOnboardingAnswer(field: OnboardingField, completed: OnboardingField[] = [], skipped: OnboardingField[] = []) {
  return {
    onboarding_completed: [...new Set([...completed, field])],
    onboarding_skipped: skipped.filter(value => value !== field),
  };
}

export function recordOnboardingSkip(field: OnboardingField, skipped: OnboardingField[] = []) {
  return [...new Set([...skipped, field])];
}
