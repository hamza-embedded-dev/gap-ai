# GAP-AI

GAP-AI is a personal AI planning assistant that helps users turn natural
language into plans, record outcomes, review follow-through, and explore
contextual and behavior-based recommendations.

The project combines a web application, a FastAPI backend, AI service
integrations, and an ESP32-S3 voice device.

## Project Status

**Development target: v1.4.0 — Documentation and Demo Improvements**

The `v1.3.0` tag represents the frozen demo baseline. This branch contains
documentation improvements and preparation for the next development version.
The existing `v1.3.0` tag will not be changed.

### Implemented Features

- **Natural-language planning:** Turn text into structured plans and review
  them before saving.
- **Voice interaction:** Send recorded audio to the backend for transcription
  and processing, then play supported spoken responses on the device.
- **Plan and outcome tracking:** Create plans and record outcomes.
- **Insights:** Review plan-follow-through analytics and available recommendations.
- **Personalization:** Configure an explicit user profile and onboarding preferences.
- **Recommendations:** Provide behavior-based, contextual, and discovery suggestions
  according to the implemented recommendation policy.
- **Voice modes:** Switch between Plan and Coach modes on the device.
- **ESP32-S3 interface:** Firmware support for an OLED, push-to-talk, accept
  and cancel buttons, I2S microphone input, speaker output, and audio feedback.
- **Demo sessions:** Support isolated demo sessions using demo seed data.

Feature availability depends on configuration, provider credentials, and
database migration status.

### Current Limitations

- The future personalized, proactive Coach experience is still planned work;
  it must not be presented as a completed capability.
- `POST /plans/{id}/reschedule`, `GET /me/export`, and `DELETE /me/data`
  are documented but are not implemented backend routes.
- Database migrations must be reviewed and verified for the target environment.
- Short device feedback tones still require further acoustic verification
  on the physical demo hardware.
- Repository code alone does not prove that external services or production
  deployments are currently available.

## Architecture

- **Backend:** FastAPI and Python.
- **Web:** React, TypeScript, and Vite.
- **AI and speech:** Nebius Token Factory/Nemotron and Groq Whisper integrations.
- **Database:** PostgreSQL/Supabase integration.
- **Device:** ESP-IDF firmware for ESP32-S3, with I2S audio and OLED support.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for architecture details and
[docs/api-contract.md](docs/api-contract.md) for endpoint contracts.

## Repository Layout

- `backend/` — FastAPI application and backend tests.
- `web/` — React and TypeScript application.
- `esp32/` — ESP-IDF device firmware.
- `ai/` — AI schemas and specifications.
- `database/` — Database migrations and SQL verification files.
- `demo/` — Demo seed data.
- `docs/` — Architecture, API contracts, deployment guidance, and project notes.

## Development Setup

Do not commit secrets or local configuration files.

### Backend

Install [uv](https://docs.astral.sh/uv/) and configure the environment
variables required by the services you want to run.

From the repository root:

```bash
uv run --directory backend --extra dev pytest
```

See [backend/README.md](backend/README.md) for backend setup details.

### Web Application

```bash
cd web
npm install
npm run dev
```

Run frontend tests and build the production bundle from the `web/` directory:

```bash
npm test
npm run build
```

### ESP32 Firmware

The firmware uses ESP-IDF. See [esp32/README.md](esp32/README.md) for wiring,
configuration, build, flashing, and serial-monitor instructions.

### Deployment

See [docs/DEPLOY.md](docs/DEPLOY.md) for deployment configuration and migration
checks. Verify the target environment before assuming database migrations
or external services are ready.

## API and Data Notes

An endpoint documented in the API contract is not necessarily implemented.
Check [docs/api-contract.md](docs/api-contract.md) before relying on a route.

## Roadmap

Potential follow-up work includes personalized proactive coaching, further
physical-device audio verification, and implementation of API capabilities
currently marked as unavailable.

## License

MIT
