-- ==============================================================================
-- Migration: 20261027_006_plan_proposals.sql
-- GAP-AI — Plan Proposals for ESP32 Action/Reject Buttons
-- ==============================================================================
--
-- This migration creates the `plan_proposals` table to support human-in-the-loop
-- plan drafting and physical button confirmation from the ESP32-S3 device.
--
-- Endpoints:
--   GET  /plans/proposals/pending
--   POST /plans/proposals/accept
--   POST /plans/proposals/reject

CREATE TABLE IF NOT EXISTS public.plan_proposals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    conversation_id uuid,
    title text NOT NULL,
    category text NOT NULL CHECK (category IN (
        'sport', 'study', 'work', 'meeting', 'health', 'social', 'personal', 'other'
    )),
    planned_start timestamptz NOT NULL,
    planned_end timestamptz NOT NULL,
    duration_minutes integer,
    recurrence_rule text,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected', 'superseded')),
    created_at timestamptz NOT NULL DEFAULT now(),
    accepted_at timestamptz,
    CONSTRAINT plan_proposals_end_after_start CHECK (planned_end >= planned_start)
);

CREATE INDEX IF NOT EXISTS plan_proposals_user_status_idx ON public.plan_proposals(user_id, status);

COMMENT ON TABLE public.plan_proposals IS
    'Actionable plan proposals awaiting physical hardware button or web confirmation.';

-- Permissions & RLS
REVOKE ALL ON TABLE public.plan_proposals FROM PUBLIC, anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.plan_proposals TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.plan_proposals TO authenticated;

ALTER TABLE public.plan_proposals ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'plan_proposals' AND policyname = 'plan_proposals_user_isolation'
    ) THEN
        CREATE POLICY plan_proposals_user_isolation ON public.plan_proposals
            FOR ALL TO authenticated
            USING (user_id = auth.uid())
            WITH CHECK (user_id = auth.uid());
    END IF;
END $$;
