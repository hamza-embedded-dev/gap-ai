export type OnboardingField =
  | 'preferred_name' | 'age_range' | 'life_context' | 'field_of_study' | 'study_year'
  | 'deadlines_goals' | 'work_schedule' | 'typical_availability' | 'interests'
  | 'skills_to_develop' | 'planning_preferences' | 'recommendation_frequency';

export type PersonalizationProfile = {
  user_id: string;
  preferred_name: string | null;
  age_range: 'under_18' | '18_24' | '25_34' | '35_44' | '45_plus' | 'prefer_not_to_say' | null;
  life_context: 'student' | 'working' | 'other' | null;
  field_of_study: string | null;
  study_year: string | null;
  deadlines_goals: Array<{ title: string; deadline: string | null; kind: 'goal' | 'exam' | 'deadline' }>;
  work_schedule: string | null;
  typical_availability: string[];
  interests: string[];
  skills_to_develop: string[];
  planning_preferences: string[];
  recommendation_frequency: 'daily' | 'weekly' | 'on_demand' | 'off' | null;
  onboarding_skipped: OnboardingField[];
  onboarding_completed: OnboardingField[];
};
