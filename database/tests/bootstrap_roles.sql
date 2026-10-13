-- database/tests/bootstrap_roles.sql
-- Idempotent provisioning of standard Supabase roles for isolated PostgreSQL testing environments.
-- This file is used only in test environments (e.g., CI service containers) where vanilla
-- PostgreSQL is used instead of a pre-configured Supabase instance.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN;
  END IF;

  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN;
  END IF;

  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN
    CREATE ROLE service_role NOLOGIN BYPASSRLS;
  ELSE
    ALTER ROLE service_role BYPASSRLS;
  END IF;
END
$$;
