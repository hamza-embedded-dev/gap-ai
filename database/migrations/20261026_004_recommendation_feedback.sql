-- Persist user-scoped recommendation feedback for selection and deduplication.
-- Apply after 20261026_003_refresh_suggestions.sql. Backend-only access follows
-- the service_role + deny-by-default RLS convention.
CREATE TABLE public.recommendation_feedback (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    recommendation_id text NOT NULL CHECK (length(recommendation_id) BETWEEN 1 AND 80),
    action text NOT NULL CHECK (action IN ('accepted', 'dismissed', 'modified')),
    rating text CHECK (rating IN ('useful', 'not_useful')),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT recommendation_feedback_action_rating CHECK (action <> 'dismissed' OR rating IS NULL)
);
CREATE INDEX recommendation_feedback_user_created_idx ON public.recommendation_feedback(user_id, created_at DESC);
CREATE INDEX recommendation_feedback_user_id_created_idx ON public.recommendation_feedback(user_id, recommendation_id, created_at DESC);
COMMENT ON COLUMN public.recommendation_feedback.recommendation_id IS 'Stable recommendation identity; dedup_key is SHA-256(source:id), while dismissal filtering uses this ID.';
REVOKE ALL ON TABLE public.recommendation_feedback FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON TABLE public.recommendation_feedback TO service_role;
ALTER TABLE public.recommendation_feedback ENABLE ROW LEVEL SECURITY;
