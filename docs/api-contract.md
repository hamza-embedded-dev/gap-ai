# GAP API Contract v0

This document is the shared interface between Backend, AI, Web and ESP32.
It is the single source of truth for request and response formats, together with `ai/schema.json`.
The mock server must expose the same endpoints, payloads, response shapes and error codes.

## Conventions

- HTTPS only. JSON (UTF-8) unless stated otherwise.
- Timestamps: ISO 8601 with timezone offset, e.g. `2026-10-06T18:00:00+03:00`.
- IDs: opaque UUID strings. No sequential identifiers.
- Plan creation accepts an optional `Idempotency-Key` header to avoid duplicates on retries.

### Error shape

    { "error": "validation_error", "message": "human readable text" }

| Code | HTTP | Meaning |
|---|---|---|
| unauthorized | 401 | Missing or invalid token |
| forbidden | 403 | Valid token, resource belongs to another user |
| not_found | 404 | Resource does not exist for this user |
| payload_too_large | 413 | Audio or body over the limit |
| validation_error | 422 | Payload does not match the contract or `ai/schema.json` |
| rate_limited | 429 | Too many requests |
| parse_failed | 502 | Model output could not be validated after retry |
| llm_unavailable | 503 | Model provider unavailable |

## Authentication

- Authenticated requests use `Authorization: Bearer <token>`.
- Access tokens are long random strings. The database stores only a hash. Raw tokens are never logged.
- First entry link `?t=<token>`: the web client reads the token once, removes it from the address bar
  (`history.replaceState`) and uses the Bearer header afterwards. The token is NOT single-use;
  it stays valid until revoked.
- Demo access is separate: `POST /demo/session` returns a token for an isolated, temporary demo user.
- Every query is scoped to the authenticated user. Authorization is enforced by the backend.

## Shared objects

**ParsedPlan** is defined in `ai/schema.json`.

**Plan**

    {
      "id": "uuid",
      "title": "Koşu",
      "category": "sport",
      "planned_start": "2026-10-06T18:00:00+03:00",
      "planned_end": "2026-10-06T19:00:00+03:00",
      "recurrence_rule": null,
      "source": "text",
      "created_at": "2026-10-05T21:10:00+03:00",
      "latest_outcome": null
    }

`source`: `text` | `voice` | `device`.

**Outcome event** (many events per plan are allowed)

    {
      "id": "uuid",
      "plan_id": "uuid",
      "status": "postponed",
      "actual_start": null,
      "postponed_to": "2026-10-08T19:00:00+03:00",
      "note": null,
      "reported_via": "web",
      "reported_at": "2026-10-06T17:00:00+03:00"
    }

`status`: `done` | `postponed` | `skipped`. `reported_via`: `web` | `device` | `auto`.

**Suggestion**

    {
      "plan_id": "uuid",
      "reason": "weather",
      "message": "Rain is expected. Thursday 19:00 is free. Move it?",
      "proposed_start": "2026-10-08T19:00:00+03:00",
      "proposed_end": "2026-10-08T20:00:00+03:00",
      "evidence": { "forecast": "rain", "adherence_pct": 66.7 }
    }

`reason`: `weather` | `pattern`. The message comes from the model; numbers and free slots are computed by the backend.

## Endpoints

### GET /health
No auth. Response: `{ "status": "ok", "version": "0.1.0" }`

### POST /demo/session
No auth. Creates an isolated demo user seeded from the demo fixture. TTL: 24 hours.

Response:

    { "token": "<raw token>", "expires_at": "2026-10-07T11:00:00+03:00", "is_demo": true }

### GET /me
Response: `{ "id": "uuid", "display_name": "Ada", "timezone": "Europe/Istanbul", "is_demo": false }`

### PATCH /me
Onboarding and profile update.

Request: `{ "display_name": "Ada", "timezone": "Europe/Istanbul" }` (both optional). Response: the updated profile.

### POST /parse
Converts natural-language text into a validated ParsedPlan. Does not write to the database.

Request:

    {
      "text": "Yarın 18'de koşuya çıkacağım.",
      "language": "tr",
      "current_date": "2026-10-05",
      "timezone": "Europe/Istanbul"
    }

Response: a ParsedPlan (see `ai/schema.json`). `language` in the request is optional.
When `intent` is `clarify`, the client shows `clarification_question` and does not create a plan.

### POST /voice
`multipart/form-data`: `audio`, `language` (optional), `current_date`, `timezone`.

Audio: HTTPS, mono PCM/WAV, 16 kHz, 16-bit, maximum 10 seconds (about 320 KB).

Response: `{ "transcript": "Yarın 18'de koşu", "parsed_plan": { ...ParsedPlan } }`

Until real speech-to-text is ready, the deployed backend may return a fixed stub transcript (documented in `docs/decisions.md`).

### POST /plans
Persists a validated plan. The backend derives `planned_start` and `planned_end` from `date`, `time`,
`duration_minutes` (default 60) and the user's timezone.

Request:

    { "parsed_plan": { ...ParsedPlan with intent "create_plan" }, "source": "text" }

Response: the created Plan (201). Rejects ParsedPlans with intent other than `create_plan` (422).

### GET /plans
Returns only the authenticated user's plans. Optional query: `from`, `to`.

Response: `{ "items": [ ...Plan ] }`

### GET /plans/{id}/suggestion
Weather and history based suggestion. Does not write to the database.

Response: `{ "suggestion": null }` or `{ "suggestion": { ...Suggestion } }`

### POST /plans/{id}/outcome
Records an outcome event.

Request:

    {
      "status": "done",
      "actual_start": "2026-10-06T18:17:00+03:00",
      "postponed_to": null,
      "note": null,
      "reported_via": "web"
    }

Response: the created Outcome event (201).
Devices may send `postponed` without `postponed_to`; analytics counts it as a postponement with unknown target.

### POST /plans/{id}/reschedule
Applies a new planned time after user approval. The original time stays recoverable through the audit log and outcome events.

Request:

    {
      "new_start": "2026-10-08T19:00:00+03:00",
      "new_end": "2026-10-08T20:00:00+03:00",
      "reason": "Moved because of rain",
      "source": "weather_suggestion"
    }

`new_end` is optional. `source`: `user` | `weather_suggestion` | `pattern_suggestion`.
Response: the updated Plan.

### GET /insights
Deterministic statistics computed by the backend. Query: `period` = `week` (default) | `last_week` | `all`.

Response:

    {
      "period": "week",
      "planned": 4,
      "done": 2,
      "postponed": 1,
      "skipped": 0,
      "unreported": 1,
      "adherence_pct": 66.7,
      "avg_start_delay_min": 17,
      "by_weekday": { "Tuesday": { "planned": 2, "done": 1, "postponed": 1 } },
      "by_hour": { "18": { "planned": 3, "done": 2 } },
      "by_category": { "sport": { "planned": 3, "done": 2 } },
      "postponed_targets": [ { "weekday": "Thursday", "hour": 19, "count": 1 } ],
      "trend_vs_prev": { "adherence_pct_delta": 12.5 },
      "narrative": "You completed 2 of 3 reported plans...",
      "is_demo": false,
      "data_label": "real"
    }

`adherence_pct` = done / (plans whose end time has passed and that have a reported outcome).
Past plans without any outcome are counted in `unreported` and excluded from the denominator.
The latest outcome of a plan decides adherence; all `postponed` events feed pattern analysis.
`narrative` may be null. `data_label`: `real` | `demo`.

### GET /me/upcoming
Upcoming plans and reminders for reminder and device layers. Optional query: `since`, `to`.

Response:

    { "items": [ { "plan_id": "uuid", "title": "Koşu", "planned_start": "2026-10-06T18:00:00+03:00", "reminder_at": "2026-10-06T17:45:00+03:00" } ] }

### GET /me/export
Exports only the authenticated user's own data (profile, plans, outcomes, cached insights). Never includes raw tokens.

### DELETE /me/data
Requires the header `X-Confirm-Delete: true`.
Deletes all user-owned records: plans, outcomes, cached insights and applicable memories.
The audit log stores that a deletion happened, never the deleted content.

Response: `{ "deleted": true, "counts": { "plans": 12, "outcomes": 15 } }`

## Integration rule

Nobody invents endpoints or payloads. Changes to this file or to `ai/schema.json` go through a pull request
reviewed by the integrator and code reviewer.
