-- Optional, user-scoped personalization data. Removing this row never affects plans.
CREATE TABLE public.personalization_profiles (
    user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    preferred_name text CHECK (preferred_name IS NULL OR length(preferred_name) <= 80),
    age_range text CHECK (age_range IS NULL OR age_range IN ('under_18','18_24','25_34','35_44','45_plus','prefer_not_to_say')),
    life_context text CHECK (life_context IS NULL OR life_context IN ('student','working','other')),
    field_of_study text CHECK (field_of_study IS NULL OR length(field_of_study) <= 120),
    study_year text CHECK (study_year IS NULL OR length(study_year) <= 40),
    deadlines_goals jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(deadlines_goals) = 'array' AND jsonb_array_length(deadlines_goals) <= 30),
    work_schedule text CHECK (work_schedule IS NULL OR length(work_schedule) <= 500),
    typical_availability jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(typical_availability) = 'array' AND jsonb_array_length(typical_availability) <= 30),
    interests jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(interests) = 'array' AND jsonb_array_length(interests) <= 30),
    skills_to_develop jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(skills_to_develop) = 'array' AND jsonb_array_length(skills_to_develop) <= 30),
    planning_preferences jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(planning_preferences) = 'array' AND jsonb_array_length(planning_preferences) <= 30),
    recommendation_frequency text CHECK (recommendation_frequency IS NULL OR recommendation_frequency IN ('daily','weekly','on_demand','off')),
    onboarding_skipped jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(onboarding_skipped) = 'array' AND jsonb_array_length(onboarding_skipped) <= 30),
    onboarding_completed jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(onboarding_completed) = 'array' AND jsonb_array_length(onboarding_completed) <= 30),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX personalization_profiles_frequency_idx ON public.personalization_profiles(recommendation_frequency) WHERE recommendation_frequency IS NOT NULL;
COMMENT ON TABLE public.personalization_profiles IS
    'Explicit user-provided personalization answers and onboarding progress only; no inferred facts or conversation transcripts. Deleting this row does not affect plans, outcomes, or suggestions.';
REVOKE ALL ON TABLE public.personalization_profiles FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.personalization_profiles TO service_role;
ALTER TABLE public.personalization_profiles ENABLE ROW LEVEL SECURITY;
