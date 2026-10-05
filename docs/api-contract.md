# GAP API Contract v0

This document is the shared interface between Backend, AI, Web and ESP32.

## Authentication

Real student sessions use a random access token.

The backend validates the token, resolves the user and performs all data access using the resolved user identity.

Raw access tokens must never be written to application logs.

Demo access is separate from student access.

## Endpoints

### POST /parse
Converts natural-language text into the validated AI schema.

### POST /voice
Receives audio and returns transcription plus parsed plan information.

Audio target:
- HTTPS
- mono PCM/WAV
- 16 kHz
- 16-bit
- maximum recording duration: 10 seconds

### POST /plans
Creates a normalized plan.

Example request:
{
  "title": "Running",
  "category": "sport",
  "planned_start": "2026-10-06T18:00:00+03:00",
  "recurrence_rule": null,
  "source": "text"
}

### GET /plans
Returns the authenticated user's plans.

### POST /plans/{id}/outcome
Records the result of a planned task.

Allowed statuses:
- done
- postponed
- skipped

Example request:
{
  "status": "done",
  "actual_start": "2026-10-06T18:17:00+03:00",
  "note": null,
  "reported_via": "web"
}

Allowed reported_via values:
- web
- device
- auto

### POST /plans/{id}/reschedule
Moves a postponed task to a new planned time.

Example request:
{
  "new_planned_start": "2026-10-08T19:00:00+03:00",
  "reason": "Moved because of rain"
}

The original planned time must remain recoverable for behavioral analysis.

### GET /insights
Returns deterministic statistics calculated by the backend.

Example:
{
  "planned": 3,
  "done": 2,
  "postponed": 1,
  "skipped": 0,
  "adherence_pct": 66.7,
  "average_start_delay_minutes": 17,
  "most_postponed_weekday": "Tuesday"
}

The backend calculates numerical statistics. Nemotron interprets the statistics and produces natural-language suggestions.

### GET /me/upcoming
Returns upcoming planisl required by reminder and device layers.

### GET /me/export
Exports the authenticated user's own data.

### DELETE /me/data
Deletes the authenticated user's data after explicit confirmation.

Deletion must cover all user-owned records, including plans, outcomes, cached insights and applicable memories.

## Integration rule

This document is the source of truth for request and response formats.
