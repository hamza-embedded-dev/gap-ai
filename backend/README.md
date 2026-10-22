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

Apply `../database/migrations/20261018_002_suggestions.sql` after it. It adds the `suggestions` table that stores the first suggestion generated for each plan (one per plan, never refreshed in the MVP); `../database/tests/verify_suggestions.sql` checks it in CI.

After applying the migrations, verify that the five core tables exist and that the backend service role has the required permissions. The idempotent create path calls the `create_plan_idempotently` RPC through Supabase PostgREST.

## Issue access tokens

There is no public sign-up endpoint. Tokens for ESP32 devices and test users are issued with an admin script that needs `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and `TOKEN_HASH_PEPPER` (the same pepper the deployed backend uses). From this directory:

```bash
uv run python -m scripts.create_access_token --display-name "ESP32 Ahmet"
uv run python -m scripts.create_access_token --user-id <user-uuid> --expires-days 30
```

`--display-name` creates a new user (`--timezone` defaults to `Europe/Istanbul`); `--user-id` adds a token to an existing non-demo user. Tokens never expire unless `--expires-days` is given.

The raw token is printed once on stdout and is not stored anywhere; the database only keeps its SHA-256 + pepper hash. Copy it straight into the device's `secrets.h` (`DEVICE_TOKEN`) or the test client. Status lines go to stderr, so `TOKEN=$(uv run python -m scripts.create_access_token ...)` captures only the token.

## Validation

Run the backend tests from this directory:

```bash
uv run --extra dev pytest
```

The backend test suite uses an in-memory store and does not require Supabase credentials. The suite passed locally with 141 tests. A separate live integration check also verified that the Supabase connection worked, the RPC created a plan, replaying the same idempotency key returned the same plan, and the temporary test user was cleaned up.
