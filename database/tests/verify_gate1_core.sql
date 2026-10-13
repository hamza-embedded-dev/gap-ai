-- database/tests/verify_gate1_core.sql
-- Comprehensive verification test suite for database/migrations/20261013_001_gate1_core.sql
-- Run with psql -v ON_ERROR_STOP=1

\set ON_ERROR_STOP on

BEGIN;

-- ==============================================================================
-- 1. STRUCTURAL AND METADATA ASSERTIONS
-- ==============================================================================
DO $$
DECLARE
  v_table_count int;
  v_rls_count int;
BEGIN
  -- 1.1 Verify all 5 core tables exist in schema public
  SELECT count(*) INTO v_table_count
    FROM information_schema.tables
   WHERE table_schema = 'public'
     AND table_name IN ('users', 'access_tokens', 'plans', 'outcomes', 'plan_creation_requests');
  IF v_table_count <> 5 THEN
    RAISE EXCEPTION 'Table check failed: expected 5 tables, found %', v_table_count;
  END IF;

  -- 1.2 Verify Row Level Security is enabled on all 5 tables
  SELECT count(*) INTO v_rls_count
    FROM pg_tables
   WHERE schemaname = 'public'
     AND tablename IN ('users', 'access_tokens', 'plans', 'outcomes', 'plan_creation_requests')
     AND rowsecurity = true;
  IF v_rls_count <> 5 THEN
    RAISE EXCEPTION 'RLS check failed: expected 5 tables with RLS enabled, found %', v_rls_count;
  END IF;

  -- 1.3 Verify required indexes exist
  PERFORM 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'access_tokens_user_id_idx';
  IF NOT FOUND THEN RAISE EXCEPTION 'Index access_tokens_user_id_idx is missing'; END IF;

  PERFORM 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'plans_user_start_idx';
  IF NOT FOUND THEN RAISE EXCEPTION 'Index plans_user_start_idx is missing'; END IF;

  PERFORM 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'outcomes_plan_user_reported_idx';
  IF NOT FOUND THEN RAISE EXCEPTION 'Index outcomes_plan_user_reported_idx is missing'; END IF;

  PERFORM 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'plan_creation_requests_plan_idx';
  IF NOT FOUND THEN RAISE EXCEPTION 'Index plan_creation_requests_plan_idx is missing'; END IF;

  -- 1.4 Verify functions exist
  PERFORM 1 FROM pg_proc WHERE proname = 'enforce_demo_token_expiry';
  IF NOT FOUND THEN RAISE EXCEPTION 'Function enforce_demo_token_expiry is missing'; END IF;

  PERFORM 1 FROM pg_proc WHERE proname = 'reject_outcome_update';
  IF NOT FOUND THEN RAISE EXCEPTION 'Function reject_outcome_update is missing'; END IF;

  PERFORM 1 FROM pg_proc WHERE proname = 'create_plan_idempotently';
  IF NOT FOUND THEN RAISE EXCEPTION 'Function create_plan_idempotently is missing'; END IF;

  -- 1.5 Verify triggers exist
  PERFORM 1 FROM pg_trigger WHERE tgname = 'access_tokens_demo_expiry_guard';
  IF NOT FOUND THEN RAISE EXCEPTION 'Trigger access_tokens_demo_expiry_guard is missing'; END IF;

  PERFORM 1 FROM pg_trigger WHERE tgname = 'outcomes_no_update';
  IF NOT FOUND THEN RAISE EXCEPTION 'Trigger outcomes_no_update is missing'; END IF;
END $$;

-- ==============================================================================
-- 2. DEMO EXPIRATION CONSTRAINT AND TRIGGER VERIFICATION
-- ==============================================================================
DO $$
DECLARE
  v_user_id uuid;
  v_non_demo_id uuid;
  v_now timestamptz := now();
  v_demo_exp timestamptz := v_now + interval '24 hours';
  v_err_code text;
  v_err_msg text;
  v_caught boolean;
BEGIN
  -- 2.1 Demo user must have demo_expires_at = created_at + 24 hours
  v_caught := false;
  BEGIN
    INSERT INTO public.users (display_name, is_demo, created_at, demo_expires_at)
    VALUES ('Invalid Demo User', true, v_now, v_now + interval '12 hours');
  EXCEPTION
    WHEN check_violation THEN
      GET STACKED DIAGNOSTICS v_err_code = RETURNED_SQLSTATE;
      IF v_err_code = '23514' THEN
        v_caught := true;
      ELSE
        RAISE;
      END IF;
  END;
  IF NOT v_caught THEN
    RAISE EXCEPTION 'Constraint users_demo_expiry_consistency failed: did not reject invalid demo_expires_at';
  END IF;

  -- 2.2 Valid demo user insertion succeeds
  INSERT INTO public.users (display_name, is_demo, created_at, demo_expires_at)
  VALUES ('Valid Demo User', true, v_now, v_demo_exp)
  RETURNING id INTO v_user_id;

  -- 2.3 Demo access token must match user's demo_expires_at
  v_caught := false;
  BEGIN
    INSERT INTO public.access_tokens (user_id, token_hash, created_at, expires_at)
    VALUES (v_user_id, 'mismatched_demo_token_hash', v_now, v_now + interval '12 hours');
  EXCEPTION
    WHEN raise_exception THEN
      GET STACKED DIAGNOSTICS v_err_code = RETURNED_SQLSTATE, v_err_msg = MESSAGE_TEXT;
      IF v_err_code = 'P0001' AND v_err_msg = 'demo access token must expire with its demo user' THEN
        v_caught := true;
      ELSE
        RAISE;
      END IF;
  END;
  IF NOT v_caught THEN
    RAISE EXCEPTION 'Trigger access_tokens_demo_expiry_guard failed: allowed mismatched demo token expiry';
  END IF;

  -- 2.4 Matching demo access token insertion succeeds
  INSERT INTO public.access_tokens (user_id, token_hash, created_at, expires_at)
  VALUES (v_user_id, 'valid_demo_token_hash', v_now, v_demo_exp);

  -- 2.5 Non-demo user allows any valid future expiration
  INSERT INTO public.users (display_name, is_demo)
  VALUES ('Regular User', false)
  RETURNING id INTO v_non_demo_id;

  INSERT INTO public.access_tokens (user_id, token_hash, created_at, expires_at)
  VALUES (v_non_demo_id, 'regular_token_hash', v_now, v_now + interval '30 days');
END $$;

-- ==============================================================================
-- 3. OUTCOME IMMUTABILITY TRIGGER VERIFICATION
-- ==============================================================================
DO $$
DECLARE
  v_user_id uuid;
  v_plan_id uuid;
  v_outcome_id uuid;
  v_err_code text;
  v_err_msg text;
  v_caught boolean;
BEGIN
  INSERT INTO public.users (display_name) VALUES ('Outcome Test User') RETURNING id INTO v_user_id;

  INSERT INTO public.plans (
    user_id, title, category, planned_start, planned_end, recurrence_rule, source
  ) VALUES (
    v_user_id, 'Evening Walk', 'sport', now(), now() + interval '45 minutes', NULL, 'web'
  ) RETURNING id INTO v_plan_id;

  INSERT INTO public.outcomes (
    plan_id, user_id, status, reported_via
  ) VALUES (
    v_plan_id, v_user_id, 'done', 'web'
  ) RETURNING id INTO v_outcome_id;

  -- 3.1 Attempting to UPDATE an outcome must be rejected by outcomes_no_update trigger
  v_caught := false;
  BEGIN
    UPDATE public.outcomes SET status = 'skipped' WHERE id = v_outcome_id;
  EXCEPTION
    WHEN raise_exception THEN
      GET STACKED DIAGNOSTICS v_err_code = RETURNED_SQLSTATE, v_err_msg = MESSAGE_TEXT;
      IF v_err_code = 'P0001' AND v_err_msg = 'outcome events are immutable; insert a new event instead' THEN
        v_caught := true;
      ELSE
        RAISE;
      END IF;
  END;
  IF NOT v_caught THEN
    RAISE EXCEPTION 'Trigger outcomes_no_update failed: allowed UPDATE on outcomes';
  END IF;
END $$;

-- ==============================================================================
-- 4. IDEMPOTENT PLAN CREATION RPC VERIFICATION
-- ==============================================================================
DO $$
DECLARE
  v_user_id uuid;
  v_start timestamptz := now() + interval '1 day';
  v_end timestamptz := now() + interval '1 day 1 hour';
  v_result jsonb;
  v_snapshot jsonb;
  v_plan_id uuid;
  v_plan_count int;
BEGIN
  INSERT INTO public.users (display_name) VALUES ('Idempotency Test User') RETURNING id INTO v_user_id;

  -- 4.1 First call: creates new plan
  v_result := public.create_plan_idempotently(
    p_user_id => v_user_id,
    p_idempotency_key => 'idem-key-001',
    p_request_hash => 'req-hash-original',
    p_title => 'Morning Jog',
    p_category => 'sport',
    p_planned_start => v_start,
    p_planned_end => v_end,
    p_recurrence_rule => NULL,
    p_source => 'text'
  );

  IF (v_result->>'conflict')::boolean IS NOT FALSE THEN
    RAISE EXCEPTION 'create_plan_idempotently failed: expected conflict=false on initial creation';
  END IF;

  v_snapshot := v_result->'response_snapshot';
  v_plan_id := (v_snapshot->>'id')::uuid;

  IF v_snapshot->>'title' <> 'Morning Jog' THEN
    RAISE EXCEPTION 'Snapshot title mismatch: got %', v_snapshot->>'title';
  END IF;
  IF v_snapshot->>'category' <> 'sport' THEN
    RAISE EXCEPTION 'Snapshot category mismatch: got %', v_snapshot->>'category';
  END IF;
  IF v_snapshot->>'source' <> 'text' THEN
    RAISE EXCEPTION 'Snapshot source mismatch: got %', v_snapshot->>'source';
  END IF;
  IF (v_snapshot->'latest_outcome') IS NOT NULL AND (v_snapshot->>'latest_outcome') IS NOT NULL THEN
    RAISE EXCEPTION 'Snapshot latest_outcome must be null on creation';
  END IF;

  -- Verify row was inserted into public.plans
  PERFORM 1 FROM public.plans WHERE id = v_plan_id AND user_id = v_user_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Plan row was not created in public.plans';
  END IF;

  -- Verify row was inserted into public.plan_creation_requests
  PERFORM 1 FROM public.plan_creation_requests
   WHERE user_id = v_user_id
     AND idempotency_key = 'idem-key-001'
     AND request_hash = 'req-hash-original'
     AND plan_id = v_plan_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Record was not created in public.plan_creation_requests';
  END IF;

  -- 4.2 Identical retry: returns same snapshot and conflict=false
  v_result := public.create_plan_idempotently(
    p_user_id => v_user_id,
    p_idempotency_key => 'idem-key-001',
    p_request_hash => 'req-hash-original',
    p_title => 'Morning Jog',
    p_category => 'sport',
    p_planned_start => v_start,
    p_planned_end => v_end,
    p_recurrence_rule => NULL,
    p_source => 'text'
  );

  IF (v_result->>'conflict')::boolean IS NOT FALSE THEN
    RAISE EXCEPTION 'create_plan_idempotently failed: expected conflict=false on identical retry';
  END IF;
  IF (v_result->'response_snapshot'->>'id')::uuid <> v_plan_id THEN
    RAISE EXCEPTION 'Idempotent replay plan_id mismatch';
  END IF;

  -- Ensure no duplicate plan was created
  SELECT count(*) INTO v_plan_count FROM public.plans WHERE user_id = v_user_id;
  IF v_plan_count <> 1 THEN
    RAISE EXCEPTION 'Duplicate plan created: expected 1 plan, found %', v_plan_count;
  END IF;

  -- 4.3 Conflicting retry: same key with differing request_hash returns conflict=true
  v_result := public.create_plan_idempotently(
    p_user_id => v_user_id,
    p_idempotency_key => 'idem-key-001',
    p_request_hash => 'req-hash-different',
    p_title => 'Evening Swimming',
    p_category => 'sport',
    p_planned_start => v_start,
    p_planned_end => v_end,
    p_recurrence_rule => NULL,
    p_source => 'text'
  );

  IF (v_result->>'conflict')::boolean IS NOT TRUE THEN
    RAISE EXCEPTION 'create_plan_idempotently failed: expected conflict=true on payload mismatch';
  END IF;
  IF (v_result->'response_snapshot'->>'id')::uuid <> v_plan_id THEN
    RAISE EXCEPTION 'Conflicting replay should return original snapshot';
  END IF;
END $$;

-- ==============================================================================
-- 5. FOREIGN KEY AND CASCADE DELETION VERIFICATION
-- ==============================================================================
DO $$
DECLARE
  v_user_id uuid;
  v_token_id uuid;
  v_result_1 jsonb;
  v_result_2 jsonb;
  v_plan_1_id uuid;
  v_plan_2_id uuid;
  v_outcome_1_id uuid;
  v_outcome_2_id uuid;
BEGIN
  -- 5.1 Provision a user with rows across all four dependent tables:
  -- - public.users
  -- - public.access_tokens
  -- - public.plans (two plans)
  -- - public.outcomes (outcomes for each plan)
  -- - public.plan_creation_requests (two requests)
  INSERT INTO public.users (display_name) VALUES ('Cascade Test User') RETURNING id INTO v_user_id;

  INSERT INTO public.access_tokens (user_id, token_hash)
  VALUES (v_user_id, 'cascade_test_token_hash')
  RETURNING id INTO v_token_id;

  v_result_1 := public.create_plan_idempotently(
    p_user_id => v_user_id,
    p_idempotency_key => 'idem-cascade-001',
    p_request_hash => 'req-hash-cascade-1',
    p_title => 'Gym Workout',
    p_category => 'sport',
    p_planned_start => now() + interval '2 hours',
    p_planned_end => now() + interval '3 hours',
    p_recurrence_rule => NULL,
    p_source => 'device'
  );
  v_plan_1_id := (v_result_1->'response_snapshot'->>'id')::uuid;

  INSERT INTO public.outcomes (
    plan_id, user_id, status, reported_via
  ) VALUES (
    v_plan_1_id, v_user_id, 'done', 'device'
  ) RETURNING id INTO v_outcome_1_id;

  v_result_2 := public.create_plan_idempotently(
    p_user_id => v_user_id,
    p_idempotency_key => 'idem-cascade-002',
    p_request_hash => 'req-hash-cascade-2',
    p_title => 'Evening Study',
    p_category => 'study',
    p_planned_start => now() + interval '5 hours',
    p_planned_end => now() + interval '6 hours',
    p_recurrence_rule => NULL,
    p_source => 'text'
  );
  v_plan_2_id := (v_result_2->'response_snapshot'->>'id')::uuid;

  INSERT INTO public.outcomes (
    plan_id, user_id, status, reported_via
  ) VALUES (
    v_plan_2_id, v_user_id, 'done', 'web'
  ) RETURNING id INTO v_outcome_2_id;

  -- 5.2 Test Plan Deletion behavior:
  -- - Deleting Plan 1 must CASCADE delete Outcome 1
  -- - Deleting Plan 1 must set plan_id to NULL in plan_creation_requests, retaining the record (ON DELETE SET NULL (plan_id))
  DELETE FROM public.plans WHERE id = v_plan_1_id;

  PERFORM 1 FROM public.outcomes WHERE id = v_outcome_1_id;
  IF FOUND THEN
    RAISE EXCEPTION 'Dependent outcome row was not cascade-deleted upon plan deletion';
  END IF;

  PERFORM 1 FROM public.plan_creation_requests
   WHERE user_id = v_user_id
     AND idempotency_key = 'idem-cascade-001'
     AND plan_id IS NULL;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'plan_creation_requests row was not retained or plan_id was not set to NULL';
  END IF;

  -- Verify Plan 2 and Outcome 2 are still intact before user deletion
  PERFORM 1 FROM public.plans WHERE id = v_plan_2_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Unrelated plan 2 was unexpectedly deleted';
  END IF;
  PERFORM 1 FROM public.outcomes WHERE id = v_outcome_2_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Unrelated outcome 2 was unexpectedly deleted';
  END IF;

  -- 5.3 Test User Deletion behavior:
  -- - Deleting User must CASCADE delete related rows from ALL applicable dependent tables:
  --   1. public.access_tokens
  --   2. public.plans
  --   3. public.outcomes
  --   4. public.plan_creation_requests
  DELETE FROM public.users WHERE id = v_user_id;

  PERFORM 1 FROM public.access_tokens WHERE user_id = v_user_id OR id = v_token_id;
  IF FOUND THEN
    RAISE EXCEPTION 'access_tokens row was not cascade-deleted upon user deletion';
  END IF;

  PERFORM 1 FROM public.plans WHERE user_id = v_user_id OR id IN (v_plan_1_id, v_plan_2_id);
  IF FOUND THEN
    RAISE EXCEPTION 'plans row was not cascade-deleted upon user deletion';
  END IF;

  PERFORM 1 FROM public.outcomes WHERE user_id = v_user_id OR id IN (v_outcome_1_id, v_outcome_2_id);
  IF FOUND THEN
    RAISE EXCEPTION 'outcomes row was not cascade-deleted upon user deletion';
  END IF;

  PERFORM 1 FROM public.plan_creation_requests
   WHERE user_id = v_user_id
      OR idempotency_key IN ('idem-cascade-001', 'idem-cascade-002');
  IF FOUND THEN
    RAISE EXCEPTION 'plan_creation_requests was not cascade-deleted upon user deletion';
  END IF;
END $$;

COMMIT;
