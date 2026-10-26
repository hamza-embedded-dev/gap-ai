-- Run with psql -v ON_ERROR_STOP=1 after the core, suggestions, and
-- personalization migrations. All inserted records are rolled back.
\set ON_ERROR_STOP on
BEGIN;
DO $$
DECLARE
  owner_id uuid;
  other_id uuid;
  plan_id uuid;
  suggestion_id uuid;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='personalization_profiles' AND rowsecurity) THEN
    RAISE EXCEPTION 'personalization_profiles is missing or RLS is disabled';
  END IF;
  IF has_table_privilege('anon','public.personalization_profiles','SELECT') OR has_table_privilege('authenticated','public.personalization_profiles','SELECT') THEN
    RAISE EXCEPTION 'client roles must not read personalization profiles directly';
  END IF;
  INSERT INTO public.users DEFAULT VALUES RETURNING id INTO owner_id;
  INSERT INTO public.users DEFAULT VALUES RETURNING id INTO other_id;
  INSERT INTO public.personalization_profiles (user_id, preferred_name, age_range, life_context, deadlines_goals, onboarding_completed)
  VALUES (owner_id, 'Sam', '18_24', 'student', '[{"title":"Exam","deadline":"2026-11-02","kind":"exam"}]', '["interests"]');
  INSERT INTO public.plans (user_id,title,category,planned_start,planned_end,source)
  VALUES (owner_id,'Study','study','2026-11-01T10:00:00Z','2026-11-01T11:00:00Z','text') RETURNING id INTO plan_id;
  INSERT INTO public.outcomes (plan_id,user_id,status,reported_via) VALUES (plan_id,owner_id,'done','web');
  INSERT INTO public.suggestions (plan_id,user_id,reason,message,proposed_start,proposed_end)
  VALUES (plan_id,owner_id,'pattern','Try another time.','2026-11-02T10:00:00Z','2026-11-02T11:00:00Z') RETURNING id INTO suggestion_id;
  INSERT INTO public.personalization_profiles (user_id, interests) VALUES (other_id, '["music"]');
  IF (SELECT interests FROM public.personalization_profiles WHERE user_id=owner_id) <> '[]'::jsonb
     OR (SELECT interests FROM public.personalization_profiles WHERE user_id=other_id) <> '["music"]'::jsonb THEN
    RAISE EXCEPTION 'profile data crossed user boundaries';
  END IF;

  -- Field clearing empties that value while retaining the other profile facts.
  UPDATE public.personalization_profiles SET interests='[]', preferred_name=preferred_name WHERE user_id=owner_id;
  IF (SELECT preferred_name FROM public.personalization_profiles WHERE user_id=owner_id) <> 'Sam' THEN
    RAISE EXCEPTION 'per-field clearing changed another field';
  END IF;

  -- Reset is a DELETE of the personalization row only; dependent product data survives.
  DELETE FROM public.personalization_profiles WHERE user_id=owner_id;
  IF NOT EXISTS (SELECT 1 FROM public.plans WHERE id=plan_id) OR NOT EXISTS (SELECT 1 FROM public.outcomes WHERE plan_id=plan_id)
     OR NOT EXISTS (SELECT 1 FROM public.suggestions WHERE id=suggestion_id) THEN
    RAISE EXCEPTION 'profile reset changed plans, outcomes, or suggestions';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.users WHERE id=owner_id) THEN
    RAISE EXCEPTION 'profile reset deleted the account';
  END IF;
END $$;
ROLLBACK;
