# GAP-AI staging deployment

This guide covers the agreed staging stack: Netlify Free for the Vite frontend,
Render Free for the Python API, the existing Supabase project through its REST
API, Nebius Token Factory for Nemotron, and Groq for Whisper.

## Render API

Create a Render **Web Service** using the Python runtime. Leave **Root
Directory** blank (repository root): backend code loads shared files from the
root `ai/` and `demo/` directories. Do not use Docker.

`backend/pyproject.toml` requires Python 3.11 or newer. Choose a supported
Python 3 version in Render. Use the existing `backend/pyproject.toml` and
`backend/uv.lock` with these commands:

Build command (run from repository root):

```bash
python -m pip install "uv==0.13.1" && uv sync --project backend --locked --no-dev
```

Render's automatic `uv` setup looks for `uv.lock` at the service root; this
repository keeps it under `backend/`, so the build installs `uv` explicitly.
`--locked` checks that the lockfile matches the project metadata.

Start command (Render's configured working directory remains repository root):

```bash
cd backend && uv run --locked uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
```

`PORT` is provided by Render. No `DATABASE_URL` is used: database access is
through Supabase PostgREST over HTTPS (`/rest/v1/` and its RPC endpoint).

## Render environment variables

Set these in Render's service settings. Values marked secret must remain
backend-only.

| Variable | Required | Purpose |
| --- | --- | --- |
| `ENVIRONMENT` | Yes: `production` | Enables production settings validation. |
| `TOKEN_HASH_PEPPER` | Yes; 32+ characters | Secret used to hash bearer tokens. |
| `SUPABASE_URL` | Yes for data routes | URL of the existing Supabase project. |
| `SUPABASE_SERVICE_KEY` | Yes for data routes; secret | Backend service key for PostgREST. Never expose it to the browser. |
| `NEBIUS_API_KEY` | For LLM features; secret | Nebius Token Factory API key. |
| `GROQ_API_KEY` | For voice transcription; secret | Groq API key. |
| `ALLOWED_ORIGINS` | Yes for browser access | Exact Netlify site origin(s), comma-separated. See CORS below. |

Optional settings recognized by `backend/app/config.py` are `NEBIUS_BASE_URL`
(`https://api.tokenfactory.nebius.com/v1`), `NEBIUS_MODEL`
(`nvidia/Nemotron-3_5-Lightning`), `NEBIUS_TIMEOUT_SECONDS` (`30.0`),
`GROQ_BASE_URL` (`https://api.groq.com/openai/v1`), `STT_PROVIDER` (`groq`),
`STT_MODEL` (`whisper-large-v3`), and `GROQ_TIMEOUT_SECONDS` (`30.0`). The
settings also accept legacy aliases `MODEL_SUPER`, `GROQ_MODEL`, and
`STT_TIMEOUT_SECONDS` respectively.

## Netlify frontend and CORS

Configure the Netlify site with base directory `web`, build command
`npm run build`, and publish directory `dist`. Set `VITE_API_URL` to the public
Render service origin, such as `https://<service>.onrender.com` (no API path or
trailing slash). This is a public URL, not a secret. Never set backend keys in
Netlify: Vite exposes `VITE_*` values in browser assets.

Set Render's `ALLOWED_ORIGINS` to the exact origin shown in the browser address
bar, including `https://` and without a path or trailing slash, for example
`https://<site>.netlify.app`. Add any custom domain or preview origin
individually as comma-separated origins. Do not use `*`. CORS settings load at
backend startup, so restart or redeploy after changing them.

## Supabase migrations

Application code does not apply migrations. Before deployment, inspect the
target database's current schema and migration history, then review and apply
the required SQL deliberately in this order:

1. `20261013_001_gate1_core.sql`
2. `20261018_002_suggestions.sql`
3. `20261026_003_refresh_suggestions.sql`
4. `20261026_003_personalization_profile.sql`
5. `20261026_004_recommendation_feedback.sql`

Run the corresponding SQL verification files against a disposable/staging
PostgreSQL database first. The current GitHub migration job applies only the
first three files; it does not yet apply/verify the personalization-profile or
recommendation-feedback migrations. No repository or CI result proves that any
of these migrations has been applied to production. Confirm that status
separately before enabling dependent features.

## Health and Free-tier behavior

`GET /health` is liveness only: it returns a static status/version response and
does not contact Supabase or check provider credentials. It is suitable as a
Render health check path, but does not prove database readiness. A separate,
minimal Supabase readiness check is a follow-up and is not currently
implemented.

Render Free web services spin down after 15 minutes without inbound traffic;
the first request after idle can take about a minute while the service wakes.
Plan demo checks with time for a cold start. Free service filesystems are
ephemeral, so do not store persistent application data locally. Current audio
handling reads bounded uploads into memory; Supabase stores application data.

Before a demo, request `/health`, then exercise a Supabase-backed authenticated
flow, one Nebius-backed request, and one supported WAV transcription. Check
Render logs for errors and verify that the Netlify origin exactly matches
`ALLOWED_ORIGINS`.
