# GAP projesi #

> It doesn't just remember your life. It understands it and acts on it.

GAP is a personal AI assistant project designed to compare what a user planned with what they did, identify behavioral patterns, and turn those patterns into practical suggestions.

## Authoritative Specifications

The project architecture, data formats, and API endpoints are strictly governed by:
- [docs/api-contract.md](docs/api-contract.md) — Sole contract for request/response payloads, error codes, and endpoints.
- [ai/schema.json](ai/schema.json) — Runtime source of truth for the `ParsedPlan` AI schema.
- [docs/decisions.md](docs/decisions.md) — Architectural and design decisions (D-001 through D-010).

Endpoints or payload fields not defined in these specifications must not be added.

## Implementation Status

### 1. Implemented
- **FastAPI Application Foundation (`backend/app/`):**
  - `GET /health`: Service health and version check (`{"status": "ok", "version": "0.1.0"}`).
  - `POST /demo/session`: Creates an isolated, temporary 24-hour demo user session and returns a secure bearer token.
  - `POST /plans`: Validates incoming plans against `ai/schema.json`, checks `create_plan` intent, derives UTC start/end timestamps using the user's timezone, and supports idempotent creation via the `Idempotency-Key` header.
- **Contract Error Handling & Security:**
  - Standardized error mapping for contractual error codes (`unauthorized`, `forbidden`, `not_found`, `payload_too_large`, `validation_error`, `rate_limited`, `parse_failed`, `llm_unavailable`).
  - Bearer token authentication with SHA-256 + pepper hashing and expiration checks.
  - Configurable CORS middleware supporting explicit allowed origins.
- **Automated Tests:**
  - Unit test suite in `backend/tests/` covering schema validation, authentication, CORS, error handling, and plan creation with in-memory stores.
  - Continuous integration via GitHub Actions (`.github/workflows/backend-tests.yml`).

### 2. Partially Implemented
- **Database Schema & PostgREST Adapter:**
  - The Gate 1 core SQL migration exists at `database/migrations/20261013_001_gate1_core.sql` (defining `users`, `access_tokens`, `plans`, `outcomes`, `plan_creation_requests`, RLS rules, and the `create_plan_idempotently` stored function). **Its execution against a live PostgreSQL/Supabase database has not yet been verified.**
  - `backend/app/db/plans.py` contains a PostgREST client implementation for Supabase, tested with mock stores.
- **Root Prototype Script:**
  - `gemini-code-1791624011543.py` is a standalone prototype script with mock endpoints. It is not integrated into `backend/app/` and does not conform to the active API contract.

### 3. Not Yet Implemented
- **Web Client (`web/`):** React / PWA application is planned; directory currently contains only placeholder files (`.gitkeep`).
- **ESP32 Firmware (`esp32/`):** Device firmware for microphone recording and outcome button reporting is planned; directory currently contains only placeholder files (`.gitkeep`).
- **AI Pipelines:**
  - `POST /parse`: Nebius Token Factory and NVIDIA Nemotron integration for natural language text parsing.
  - `POST /voice`: Groq Whisper Large V3 integration for speech-to-text audio processing.
- **Remaining API Endpoints:**
  - `GET /plans`, `POST /plans/{id}/outcome`, `POST /plans/{id}/reschedule`, `GET /plans/{id}/suggestion`, `GET /insights`, `GET /me`, `PATCH /me`, `GET /me/upcoming`, `GET /me/export`, `DELETE /me/data`.
- **Weather & GAP Analytics:** Weather API integration for suggestions and deterministic adherence calculation engine.

## Core Flow (Intended Product Architecture)

The sequence below describes the target product architecture and end-to-end data flow once all components are integrated, rather than currently operational functionality:

Text or voice input
→ structured plan
→ persistent plan history
→ user outcome
→ deterministic behavior analysis
→ Nemotron interpretation
→ proactive suggestion

## Technology

- FastAPI backend
- PostgreSQL / Supabase
- React / PWA
- NVIDIA Nemotron through Nebius Token Factory
- Groq Whisper Large V3 (Speech-to-Text)
- Weather-based suggestions (MVP target)
- Optional ESP32 experience (I2S audio & physical buttons)

## Repository Structure

- `backend/` — FastAPI backend application, schemas, PostgREST adapter, and test suite
- `ai/` — authoritative JSON schema (`ai/schema.json`); prompt templates and model pipelines to be added
- `web/` — React / PWA web application (placeholder; implementation sprint target)
- `database/` — SQL migrations (`database/migrations/`) and schema reference documents; seed data not yet present
- `esp32/` — ESP32 firmware source code (placeholder; hardware implementation sprint target)
- `docs/` — API contract (`api-contract.md`), architectural decisions (`decisions.md`), architecture, and task tracking
- `demo/` — demo scripts and presentation materials (placeholder)

## Development

Secrets must never be committed to the repository.

1. Copy `.env.example` to `.env` and fill in local credentials:
   ```bash
   cp .env.example .env
   ```
2. Run backend tests from the repository root (requires [uv](https://docs.astral.sh/uv/)):
   ```bash
   uv run --directory backend --extra dev pytest
   ```
   *(Alternatively: `cd backend && uv run --extra dev pytest`)*

## License

MIT

