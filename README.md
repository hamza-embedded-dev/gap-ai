# GAP-AI

GAP-AI is a personal planning assistant that records plans and outcomes, summarizes patterns in follow-through, and can offer a suggestion based on history and weather.

## Project status

This section describes what is present in the repository. Code being present does not by itself confirm a live deployment or a successful end-to-end run against external services.

### Implemented in the repository

- **Backend (`backend/`):** FastAPI routes for health, demo sessions, profiles, plan creation/listing, outcomes, text parsing, voice transcription, upcoming plans, insights, and suggestions.
- **Plan flow:** Text is parsed into the shared `ParsedPlan` schema, can be reviewed in the web app, then saved with an optional idempotency key. Plans can be listed and outcome events recorded.
- **AI integrations:** Nebius Token Factory/Nemotron client for structured plan parsing and suggestion wording; Groq Whisper client for voice transcription. Provider use requires valid runtime credentials and has not been verified by this repository status description.
- **Analytics:** A deterministic backend analytics module calculates adherence and plan/outcome breakdowns; the web app has an insights dashboard.
- **Database:** PostgreSQL/Supabase migrations define the core tables and saved suggestions. The backend includes a Supabase PostgREST adapter.
- **Demo data:** `POST /demo/session` creates an isolated demo user and seeds it from `demo/seed/demo_plans.json`.
- **ESP32:** ESP-IDF firmware connects to Wi-Fi and checks `GET /health`. An I2S WAV recording module is present, but device upload to `/voice`, outcome buttons, and display integration are not implemented in the current firmware flow.

### Not implemented in the current backend

The API contract also describes `POST /plans/{id}/reschedule`, `GET /me/export`, and `DELETE /me/data`; these routes are not currently registered in the FastAPI application. See the implementation notes in [docs/api-contract.md](docs/api-contract.md).

The repository does not establish that the web app or backend is currently deployed, nor that the live Supabase, Nebius, Groq, or ESP32 hardware flows have passed end-to-end verification. See [docs/DEPLOY.md](docs/DEPLOY.md) for the staging setup and verification procedure.

## Architecture and specifications

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — intended architecture and component flow.
- [docs/api-contract.md](docs/api-contract.md) — API payload contract, with route implementation status.
- [ai/schema.json](ai/schema.json) — runtime source of truth for `ParsedPlan` validation.
- [docs/decisions.md](docs/decisions.md) — recorded architectural decisions.
- [docs/TASKS.md](docs/TASKS.md) — current repository-based task status and remaining work.

## Repository layout

- `backend/` — FastAPI application, Supabase adapter, AI clients, analytics, and backend tests.
- `web/` — React, TypeScript, and Vite client.
- `ai/` — `ParsedPlan` schema, prompt, and parsing evaluation cases.
- `database/` — PostgreSQL migrations, SQL verification scripts, and schema references.
- `esp32/` — ESP-IDF firmware and I2S recording module.
- `demo/` — synthetic seed data for isolated demo sessions.
- `docs/` — architecture, API contract, deployment guidance, decisions, and task status.

## Development

Do not commit secrets. Copy `.env.example` to `.env` and configure the variables needed for the services you run.

Run backend tests from the repository root (requires [uv](https://docs.astral.sh/uv/)):

```bash
uv run --directory backend --extra dev pytest
```

Run the web client from `web/`:

```bash
npm install
npm run dev
```

The web package also defines `npm test` and `npm run build`. The backend and frontend setup details are in [backend/README.md](backend/README.md) and [docs/DEPLOY.md](docs/DEPLOY.md).

## License

MIT
