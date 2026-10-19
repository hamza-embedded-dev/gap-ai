-- Saved plan suggestions (B3-7, K-5, api-contract "GET /plans/{id}/suggestion").
-- Apply after 20261013_001_gate1_core.sql. Same conventions as the core
-- migration: schema-qualified objects, only service_role has table access.
--
-- MVP rule: the first suggestion generated for a plan is stored and returned on
-- every later request; it is never refreshed. Hence one row per plan and no
-- UPDATE privilege.

CREATE TABLE public.suggestions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id uuid NOT NULL,
    user_id uuid NOT NULL,
    reason text NOT NULL CHECK (reason IN ('weather', 'pattern')),
    message text NOT NULL,
    proposed_start timestamptz NOT NULL,
    proposed_end timestamptz NOT NULL,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT suggestions_plan_owner_fk FOREIGN KEY (plan_id, user_id)
        REFERENCES public.plans(id, user_id) ON DELETE CASCADE,
    CONSTRAINT suggestions_one_per_plan UNIQUE (plan_id),
    CONSTRAINT suggestions_end_after_start CHECK (proposed_end > proposed_start),
    CONSTRAINT suggestions_evidence_is_object CHECK (jsonb_typeof(evidence) = 'object')
);

COMMENT ON TABLE public.suggestions IS
    'First suggestion generated for a plan; returned unchanged on later requests (no refresh in MVP).';
COMMENT ON COLUMN public.suggestions.evidence IS
    'Contract evidence object, e.g. {"forecast": "rain", "adherence_pct": 66.7}.';

REVOKE ALL ON TABLE public.suggestions FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, DELETE ON TABLE public.suggestions TO service_role;

ALTER TABLE public.suggestions ENABLE ROW LEVEL SECURITY;
