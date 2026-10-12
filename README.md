# GAP #

> It doesn't just remember your life. It understands it and acts on it.

GAP is a personal AI assistant project intended to compare what a user planned with what they did, identify behavioral patterns, and turn those patterns into practical suggestions.

## Implementation status

This repository currently contains project documentation, the shared API contract and AI schema, and a mock FastAPI prototype. The production backend, database migrations, React/PWA client, and ESP32 firmware are not yet present. The flow below describes the intended product, not a completed implementation. Text responses are required; text-to-speech (TTS) is optional for the MVP.

## Core flow

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
- Weather-based suggestions (MVP target)
- Optional ESP32 experience

## Repository structure

- `backend/` — FastAPI backend
- `ai/` — prompts, schemas and AI logic
- `web/` — web application
- `database/` — database schema and seed data
- `esp32/` — device firmware
- `docs/` — architecture, API contract and decisions
- `demo/` — demo and video materials

## Development

Secrets must never be committed to the repository.

Copy `.env.example` to `.env` and fill in local credentials.

## License

MIT
