# GAP-AI backend foundation

This directory contains the initial FastAPI application foundation. The API contract remains in `../docs/api-contract.md`, and `../ai/schema.json` is the runtime source of truth for `ParsedPlan` validation.

## Install and run

Install [uv](https://docs.astral.sh/uv/), then from this directory:

```powershell
uv sync --extra dev
uv run uvicorn app.main:app --reload
```

## Run tests

From this directory:

```powershell
uv run --extra dev pytest
```

The `/plans` endpoint uses the configured Supabase PostgREST API. Set `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and `TOKEN_HASH_PEPPER`; production requires the pepper to contain at least 32 characters. Keep secrets in your local `.env` file and never commit them.

## Supabase database setup

The schema migration is `../database/migrations/20261013_001_gate1_core.sql`. It was applied through the Supabase SQL Editor for the development project. It creates the core tables, constraints, indexes, triggers, row-level security settings, grants, and the `create_plan_idempotently` RPC. The migration targets PostgreSQL 15 or newer.

After applying the migration, verify that the five core tables exist and that the backend service role has the required permissions. The idempotent create path calls the `create_plan_idempotently` RPC through Supabase PostgREST.

## Validation

Run the backend tests from this directory:

```bash
uv run --extra dev pytest
```

The backend test suite uses an in-memory store and does not require Supabase credentials. The suite passed locally with 141 tests. A separate live integration check also verified that the Supabase connection worked, the RPC created a plan, replaying the same idempotency key returned the same plan, and the temporary test user was cleaned up.
