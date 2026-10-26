-- Allow the backend to refresh a saved recommendation after a newer outcome.
-- The application considers a row stale when any latest plan outcome has a
-- reported_at timestamp newer than suggestions.created_at.
GRANT UPDATE (reason, message, proposed_start, proposed_end, evidence, created_at)
    ON TABLE public.suggestions TO service_role;

COMMENT ON TABLE public.suggestions IS
    'One saved recommendation per plan; refreshed only after a newer plan outcome is reported.';
