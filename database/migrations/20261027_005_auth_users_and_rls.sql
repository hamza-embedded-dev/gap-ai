-- ==============================================================================
-- Migration: 20261027_005_auth_users_and_rls.sql
-- GAP-AI — Google OAuth 2.0 with Supabase Auth & Row Level Security (RLS)
-- ==============================================================================
--
-- This migration:
-- 1. Sets up an automatic trigger to synchronize Supabase Auth users (auth.users)
--    with the public application users table (public.users) upon Google OAuth sign-in.
-- 2. Grants appropriate schema and table permissions to the 'authenticated' role.
-- 3. Implements Row Level Security (RLS) policies for user data isolation
--    (plans, outcomes, personalization profiles, access tokens).
--
-- Intended deployment: Supabase PostgreSQL database.

-- 1. Automatic sync trigger from auth.users -> public.users
CREATE OR REPLACE FUNCTION public.handle_auth_user_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_display_name text;
BEGIN
    -- Extract display name from user_metadata (Google full_name or name) or fallback to email
    v_display_name := COALESCE(
        NEW.raw_user_meta_data->>'full_name',
        NEW.raw_user_meta_data->>'name',
        NEW.raw_user_meta_data->>'user_name',
        split_part(NEW.email, '@', 1)
    );

    INSERT INTO public.users (id, display_name, timezone, is_demo, created_at, demo_expires_at)
    VALUES (
        NEW.id,
        v_display_name,
        'Europe/Istanbul',
        false,
        NEW.created_at,
        NULL
    )
    ON CONFLICT (id) DO UPDATE SET
        display_name = COALESCE(EXCLUDED.display_name, public.users.display_name);

    RETURN NEW;
END;
$$;

-- Drop existing trigger if present to ensure clean idempotency
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT OR UPDATE ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_auth_user_change();

-- 2. Grant permissions to authenticated role for direct Supabase client queries
GRANT USAGE ON SCHEMA public TO authenticated;

GRANT SELECT, UPDATE ON TABLE public.users TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.plans TO authenticated;
GRANT SELECT, INSERT ON TABLE public.outcomes TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.personalization_profiles TO authenticated;
GRANT SELECT ON TABLE public.access_tokens TO authenticated;

-- 3. Row Level Security (RLS) Policies
-- Ensure RLS is active on all user data tables
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.personalization_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.access_tokens ENABLE ROW LEVEL SECURITY;

-- Users table RLS
DROP POLICY IF EXISTS "Users can view own profile" ON public.users;
CREATE POLICY "Users can view own profile" ON public.users
    FOR SELECT TO authenticated
    USING (auth.uid() = id);

DROP POLICY IF EXISTS "Users can update own profile" ON public.users;
CREATE POLICY "Users can update own profile" ON public.users
    FOR UPDATE TO authenticated
    USING (auth.uid() = id)
    WITH CHECK (auth.uid() = id);

-- Plans table RLS
DROP POLICY IF EXISTS "Users can view own plans" ON public.plans;
CREATE POLICY "Users can view own plans" ON public.plans
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own plans" ON public.plans;
CREATE POLICY "Users can insert own plans" ON public.plans
    FOR INSERT TO authenticated
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own plans" ON public.plans;
CREATE POLICY "Users can update own plans" ON public.plans
    FOR UPDATE TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete own plans" ON public.plans;
CREATE POLICY "Users can delete own plans" ON public.plans
    FOR DELETE TO authenticated
    USING (auth.uid() = user_id);

-- Outcomes table RLS (Append-only event log)
DROP POLICY IF EXISTS "Users can view own outcomes" ON public.outcomes;
CREATE POLICY "Users can view own outcomes" ON public.outcomes
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own outcomes" ON public.outcomes;
CREATE POLICY "Users can insert own outcomes" ON public.outcomes
    FOR INSERT TO authenticated
    WITH CHECK (auth.uid() = user_id);

-- Personalization profiles RLS
DROP POLICY IF EXISTS "Users can view own personalization" ON public.personalization_profiles;
CREATE POLICY "Users can view own personalization" ON public.personalization_profiles
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can manage own personalization" ON public.personalization_profiles;
CREATE POLICY "Users can manage own personalization" ON public.personalization_profiles
    FOR ALL TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Access tokens table RLS (Users can only view their own tokens)
DROP POLICY IF EXISTS "Users can view own access tokens" ON public.access_tokens;
CREATE POLICY "Users can view own access tokens" ON public.access_tokens
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id);
