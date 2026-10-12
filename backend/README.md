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

Production configuration fails closed: set `ENVIRONMENT=production` and provide a `TOKEN_HASH_PEPPER` containing at least 32 characters. No secret has a fallback value. Provider/database settings are intentionally not validated until those integrations are implemented.
