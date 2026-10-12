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

The `/plans` endpoint uses the configured Supabase PostgREST API. Set `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and `TOKEN_HASH_PEPPER`; production requires the pepper to contain at least 32 characters. The idempotent create path calls `create_plan_idempotently` from `../database/migrations/20261013_001_gate1_core.sql`, which must be installed in PostgreSQL 15 or newer. Tests use an in-memory store and do not require Supabase credentials. The migration has not been executed or validated against PostgreSQL; the backend test suite does not execute SQL.
