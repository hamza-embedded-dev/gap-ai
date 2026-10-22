-- database/tests/verify_suggestions.sql
-- Verification for database/migrations/20261018_002_suggestions.sql.
-- Run with psql -v ON_ERROR_STOP=1 after both migrations. Everything is rolled back.

\set ON_ERROR_STOP on

BEGIN;

DO $$
DECLARE
  v_user_id uuid;
  v_other_user_id uuid;
  v_plan_id uuid;
  v_other_plan_id uuid;
BEGIN
  -- 1. Structure and privileges
  PERFORM 1 FROM pg_tables
   WHERE schemaname = 'public' AND tablename = 'suggestions' AND rowsecurity = true;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'suggestions table is missing or RLS is disabled';
  END IF;

  IF has_table_privilege('anon', 'public.suggestions', 'SELECT')
     OR has_table_privilege('authenticated', 'public.suggestions', 'SELECT') THEN
    RAISE EXCEPTION 'client roles must not read suggestions';
  END IF;
  IF NOT has_table_privilege('service_role', 'public.suggestions', 'SELECT')
     OR NOT has_table_privilege('service_role', 'public.suggestions', 'INSERT') THEN
    RAISE EXCEPTION 'service_role must read and insert suggestions';
  END IF;
  IF has_table_privilege('service_role', 'public.suggestions', 'UPDATE') THEN
    RAISE EXCEPTION 'saved suggestions must not be updated (no refresh in MVP)';
  END IF;

  -- Fixtures
  INSERT INTO public.users (display_name) VALUES ('Suggestion Owner') RETURNING id INTO v_user_id;
  INSERT INTO public.users (display_name) VALUES ('Other User') RETURNING id INTO v_other_user_id;
  INSERT INTO public.plans (user_id, title, category, planned_start, planned_end, source)
  VALUES (v_user_id, 'Run', 'sport', '2026-10-08T18:00:00+03:00', '2026-10-08T19:00:00+03:00', 'text')
  RETURNING id INTO v_plan_id;
  INSERT INTO public.plans (user_id, title, category, planned_start, planned_end, source)
  VALUES (v_other_user_id, 'Study', 'study', '2026-10-08T18:00:00+03:00', '2026-10-08T19:00:00+03:00', 'text')
  RETURNING id INTO v_other_plan_id;

  -- 2. A valid suggestion is stored with its evidence object
  INSERT INTO public.suggestions (plan_id, user_id, reason, message, proposed_start, proposed_end, evidence)
  VALUES (v_plan_id, v_user_id, 'weather', 'Rain expected.',
          '2026-10-09T19:00:00+03:00', '2026-10-09T20:00:00+03:00',
          '{"forecast": "rain", "adherence_pct": 66.7}');

  PERFORM 1 FROM public.suggestions
   WHERE plan_id = v_plan_id AND user_id = v_user_id AND evidence ->> 'forecast' = 'rain';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'valid suggestion was not stored';
  END IF;

  -- 3. Only one suggestion per plan
  BEGIN
    INSERT INTO public.suggestions (plan_id, user_id, reason, message, proposed_start, proposed_end)
    VALUES (v_plan_id, v_user_id, 'pattern', 'Second one.',
            '2026-10-10T19:00:00+03:00', '2026-10-10T20:00:00+03:00');
    RAISE EXCEPTION 'second suggestion for the same plan was accepted';
  EXCEPTION WHEN unique_violation THEN
    NULL;
  END;

  -- 4. Tenant isolation: a suggestion cannot point at another user's plan
  BEGIN
    INSERT INTO public.suggestions (plan_id, user_id, reason, message, proposed_start, proposed_end)
    VALUES (v_other_plan_id, v_user_id, 'weather', 'Cross-tenant.',
            '2026-10-10T19:00:00+03:00', '2026-10-10T20:00:00+03:00');
    RAISE EXCEPTION 'suggestion for another user''s plan was accepted';
  EXCEPTION WHEN foreign_key_violation THEN
    NULL;
  END;

  -- 5. Field constraints
  BEGIN
    INSERT INTO public.suggestions (plan_id, user_id, reason, message, proposed_start, proposed_end)
    VALUES (v_other_plan_id, v_other_user_id, 'mood', 'Bad reason.',
            '2026-10-10T19:00:00+03:00', '2026-10-10T20:00:00+03:00');
    RAISE EXCEPTION 'unknown reason was accepted';
  EXCEPTION WHEN check_violation THEN
    NULL;
  END;

  BEGIN
    INSERT INTO public.suggestions (plan_id, user_id, reason, message, proposed_start, proposed_end)
    VALUES (v_other_plan_id, v_other_user_id, 'weather', 'Ends before it starts.',
            '2026-10-10T20:00:00+03:00', '2026-10-10T19:00:00+03:00');
    RAISE EXCEPTION 'proposed_end before proposed_start was accepted';
  EXCEPTION WHEN check_violation THEN
    NULL;
  END;

  BEGIN
    INSERT INTO public.suggestions (plan_id, user_id, reason, message, proposed_start, proposed_end, evidence)
    VALUES (v_other_plan_id, v_other_user_id, 'weather', 'Evidence is a list.',
            '2026-10-10T19:00:00+03:00', '2026-10-10T20:00:00+03:00', '[1, 2]');
    RAISE EXCEPTION 'non-object evidence was accepted';
  EXCEPTION WHEN check_violation THEN
    NULL;
  END;

  -- 6. Deleting the plan removes its suggestion; deleting the user does too
  DELETE FROM public.plans WHERE id = v_plan_id;
  PERFORM 1 FROM public.suggestions WHERE plan_id = v_plan_id;
  IF FOUND THEN
    RAISE EXCEPTION 'suggestion was not cascade-deleted with its plan';
  END IF;

  INSERT INTO public.suggestions (plan_id, user_id, reason, message, proposed_start, proposed_end)
  VALUES (v_other_plan_id, v_other_user_id, 'pattern', 'Try earlier.',
          '2026-10-10T17:00:00+03:00', '2026-10-10T18:00:00+03:00');
  DELETE FROM public.users WHERE id = v_other_user_id;
  PERFORM 1 FROM public.suggestions WHERE user_id = v_other_user_id;
  IF FOUND THEN
    RAISE EXCEPTION 'suggestion was not cascade-deleted with its user';
  END IF;
END $$;

ROLLBACK;
