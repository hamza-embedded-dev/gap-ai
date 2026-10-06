# Decisions

Short log of decisions and the reason for each. Newest at the bottom.

## D-001 (2026-10-06) Backend authorization is primary
Access uses custom tokens, not Supabase Auth. The backend resolves the user and scopes every query.
Row Level Security is only mentioned in the README if it is actually configured and tested.

## D-002 (2026-10-06) Access tokens
Only a hash is stored. The `?t=` entry link is read once by the client and removed from the address bar;
afterwards the Bearer header is used. The token is not single-use and can be revoked.

## D-003 (2026-10-06) Isolated demo sessions
`POST /demo/session` creates a temporary demo user from the demo fixture (24 h TTL),
so jury members never see each other's data. Demo data is always labeled as sample data.

## D-004 (2026-10-06) One AI schema
`ai/schema.json` is the only AI output schema. Intents: `create_plan`, `clarify`, `unsupported`.
Ambiguous input produces `clarify` with a question instead of a guess.

## D-005 (2026-10-06) Outcome history
A plan can have many outcome events. `postponed_to` is optional (devices may omit it) so postponement patterns stay analyzable.

## D-006 (2026-10-06) Plan normalization
The backend derives `planned_start` and `planned_end` from the ParsedPlan, the user's timezone and
`duration_minutes` (default 60 minutes).

## D-007 (2026-10-06) Nebius Serverless
Target: run the reminder scheduler as a Nebius Serverless Job. Fallback: run it with the backend host
and document that honestly in the README. The Token Factory runtime call already satisfies the platform requirement.

## D-008 (2026-10-06) Internal planning documents
The detailed internal plan and task board (Turkish) stay outside the public repository.
The public repository only contains English submission material. Event credit codes are never committed.
