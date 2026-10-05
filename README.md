# GAP

> It doesn't just remember your life. It understands it and acts on it.

GAP is a Personal AI assistant that compares what you planned with what you actually did, learns behavioral patterns, and turns those patterns into practical suggestions.

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
- Weather tool
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
