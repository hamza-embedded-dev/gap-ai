-- Gate 1 core schema for the custom-token FastAPI backend.
-- Apply only through the project's future migration workflow; this file is not
-- executed by the repository's test suite.
--
-- Every object is explicitly schema-qualified with `public`; the migration does
-- not change the session search_path. Intended deployment: Supabase (PostgreSQL
-- 15+ with the anon, authenticated and service_role roles already present).

CREATE TABLE public.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name text,
    timezone text NOT NULL DEFAULT 'Europe/Istanbul',
    is_demo boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    demo_expires_at timestamptz,
    CONSTRAINT users_demo_expiry_consistency CHECK (
        (is_demo AND demo_expires_at IS NOT NULL AND demo_expires_at = created_at + interval '24 hours')
        OR (NOT is_demo AND demo_expires_at IS NULL)
    )
);

COMMENT ON COLUMN public.users.timezone IS
    'IANA timezone name; validate against the application timezone database before insert/update.';

CREATE TABLE public.access_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    revoked_at timestamptz,
    CONSTRAINT access_tokens_hash_nonempty CHECK (length(token_hash) > 0),
    CONSTRAINT access_tokens_expiry_after_creation CHECK (expires_at IS NULL OR expires_at > created_at),
    CONSTRAINT access_tokens_revoked_after_creation CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);

CREATE INDEX access_tokens_user_id_idx ON public.access_tokens(user_id);

-- A demo token has the same 24-hour expiry as its isolated demo user. Expiry
-- checks against the current time and revocation checks remain authentication
-- responsibilities in the backend.
CREATE FUNCTION public.enforce_demo_token_expiry() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    user_is_demo boolean;
    user_demo_expires_at timestamptz;
BEGIN
    SELECT is_demo, demo_expires_at
      INTO user_is_demo, user_demo_expires_at
      FROM public.users
     WHERE id = NEW.user_id;

    IF user_is_demo AND NEW.expires_at IS DISTINCT FROM user_demo_expires_at THEN
        RAISE EXCEPTION 'demo access token must expire with its demo user';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER access_tokens_demo_expiry_guard
    BEFORE INSERT OR UPDATE OF user_id, expires_at ON public.access_tokens
    FOR EACH ROW EXECUTE FUNCTION public.enforce_demo_token_expiry();

CREATE TABLE public.plans (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title text NOT NULL,
    category text NOT NULL CHECK (category IN (
        'sport', 'study', 'work', 'meeting', 'health', 'social', 'personal', 'other'
    )),
    planned_start timestamptz NOT NULL,
    planned_end timestamptz NOT NULL,
    recurrence_rule text,
    source text NOT NULL CHECK (source IN ('text', 'voice', 'device')),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT plans_end_after_start CHECK (planned_end > planned_start),
    CONSTRAINT plans_id_user_unique UNIQUE (id, user_id)
);

CREATE INDEX plans_user_start_idx ON public.plans(user_id, planned_start);

CREATE TABLE public.outcomes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id uuid NOT NULL,
    user_id uuid NOT NULL,
    status text NOT NULL CHECK (status IN ('done', 'postponed', 'skipped')),
    actual_start timestamptz,
    postponed_to timestamptz,
    note text,
    reported_via text NOT NULL CHECK (reported_via IN ('web', 'device', 'auto')),
    reported_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT outcomes_plan_owner_fk FOREIGN KEY (plan_id, user_id)
        REFERENCES public.plans(id, user_id) ON DELETE CASCADE
);

CREATE INDEX outcomes_plan_user_reported_idx ON public.outcomes(plan_id, user_id, reported_at DESC, id DESC);

-- Event history rows cannot be edited. FK cascade DELETEs do not invoke this
-- UPDATE trigger, so user-data and plan deletion can still purge their events.
CREATE FUNCTION public.reject_outcome_update() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION 'outcome events are immutable; insert a new event instead';
END;
$$;

CREATE TRIGGER outcomes_no_update
    BEFORE UPDATE ON public.outcomes
    FOR EACH ROW EXECUTE FUNCTION public.reject_outcome_update();

CREATE TABLE public.plan_creation_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    idempotency_key text NOT NULL,
    request_hash text NOT NULL,
    plan_id uuid,
    response_snapshot jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT plan_creation_requests_key_nonempty CHECK (length(idempotency_key) > 0),
    CONSTRAINT plan_creation_requests_hash_nonempty CHECK (length(request_hash) > 0),
    CONSTRAINT plan_creation_requests_owner_key_unique UNIQUE (user_id, idempotency_key),
    CONSTRAINT plan_creation_requests_plan_owner_fk FOREIGN KEY (plan_id, user_id)
        REFERENCES public.plans(id, user_id) ON DELETE SET NULL (plan_id)
);

CREATE INDEX plan_creation_requests_plan_idx ON public.plan_creation_requests(plan_id);

COMMENT ON COLUMN public.plan_creation_requests.plan_id IS
    'Set to NULL if the plan is deleted; retain the per-user key and response snapshot for contract-defined idempotent replay.';
COMMENT ON COLUMN public.access_tokens.token_hash IS
    'Store only a one-way token digest; raw bearer tokens must never be persisted. The digest algorithm and encoding are intentionally unspecified here.';
COMMENT ON TABLE public.outcomes IS
    'Outcome rows are event history: append new events and do not update existing events. User-data purge may delete them via the plan/user cascades.';
COMMENT ON COLUMN public.plan_creation_requests.request_hash IS
    'Opaque digest of the canonical request payload, used to reject key reuse with a different request. Algorithm and encoding must match the backend implementation.';
COMMENT ON COLUMN public.plan_creation_requests.response_snapshot IS
    'Original create response returned on an idempotent replay, even if the plan changes or is deleted later.';

-- PostgREST exposes each RPC call as one PostgreSQL transaction. This function
-- checks the key before creating a plan, and resolves concurrent insert races
-- through the unique (user_id, idempotency_key) constraint.
CREATE FUNCTION public.create_plan_idempotently(
    p_user_id uuid,
    p_idempotency_key text,
    p_request_hash text,
    p_title text,
    p_category text,
    p_planned_start timestamptz,
    p_planned_end timestamptz,
    p_recurrence_rule text,
    p_source text
) RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    saved_request plan_creation_requests%ROWTYPE;
    new_plan plans%ROWTYPE;
    new_request_id uuid;
    snapshot jsonb;
BEGIN
    SELECT * INTO saved_request
      FROM plan_creation_requests
     WHERE user_id = p_user_id AND idempotency_key = p_idempotency_key;

    IF FOUND THEN
        RETURN jsonb_build_object(
            'conflict', saved_request.request_hash <> p_request_hash,
            'response_snapshot', saved_request.response_snapshot
        );
    END IF;

    INSERT INTO plans (
        user_id, title, category, planned_start, planned_end, recurrence_rule, source
    ) VALUES (
        p_user_id, p_title, p_category, p_planned_start, p_planned_end, p_recurrence_rule, p_source
    ) RETURNING * INTO new_plan;

    snapshot := jsonb_build_object(
        'id', new_plan.id,
        'title', new_plan.title,
        'category', new_plan.category,
        'planned_start', new_plan.planned_start,
        'planned_end', new_plan.planned_end,
        'recurrence_rule', new_plan.recurrence_rule,
        'source', new_plan.source,
        'created_at', new_plan.created_at,
        'latest_outcome', NULL
    );

    INSERT INTO plan_creation_requests (
        user_id, idempotency_key, request_hash, plan_id, response_snapshot
    ) VALUES (
        p_user_id, p_idempotency_key, p_request_hash, new_plan.id, snapshot
    ) ON CONFLICT (user_id, idempotency_key) DO NOTHING
    RETURNING id INTO new_request_id;

    IF new_request_id IS NULL THEN
        -- Another transaction won the unique-key race. Remove this transaction's
        -- temporary plan, then return the winner's snapshot or hash conflict.
        DELETE FROM plans WHERE id = new_plan.id AND user_id = p_user_id;
        SELECT * INTO saved_request
          FROM plan_creation_requests
         WHERE user_id = p_user_id AND idempotency_key = p_idempotency_key;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'idempotency record disappeared during conflict resolution';
        END IF;

        RETURN jsonb_build_object(
            'conflict', saved_request.request_hash <> p_request_hash,
            'response_snapshot', saved_request.response_snapshot
        );
    END IF;

    RETURN jsonb_build_object('conflict', false, 'response_snapshot', snapshot);
END;
$$;

-- Privileges. Supabase's default privileges for objects created in `public` can
-- grant access directly to anon and authenticated; REVOKE ... FROM PUBLIC does
-- not remove those direct grants, so each role is revoked explicitly. Only the
-- server-side service_role (used by the FastAPI backend) keeps access.
GRANT USAGE ON SCHEMA public TO service_role;

REVOKE ALL ON FUNCTION public.create_plan_idempotently(
    uuid, text, text, text, text, timestamptz, timestamptz, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_plan_idempotently(
    uuid, text, text, text, text, timestamptz, timestamptz, text, text
) TO service_role;

REVOKE ALL ON TABLE
    public.users, public.access_tokens, public.plans, public.outcomes,
    public.plan_creation_requests
FROM PUBLIC, anon, authenticated;

-- Minimum table access for the backend. outcomes has no UPDATE: events are
-- immutable (see outcomes_no_update). service_role also bypasses RLS in Supabase.
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    public.users, public.access_tokens, public.plans, public.plan_creation_requests
TO service_role;
GRANT SELECT, INSERT, DELETE ON TABLE public.outcomes TO service_role;

-- Defense in depth: RLS with no policies denies client roles even if a table
-- privilege is granted to them later. No client-access policies are defined;
-- authorization is performed by the backend (D-001).
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.access_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plan_creation_requests ENABLE ROW LEVEL SECURITY;
