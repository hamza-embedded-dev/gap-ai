# GAP-AI Web Client

The web client is a React and TypeScript application built with Vite. It provides:

- Demo session creation and bearer-token handling.
- Natural-language plan entry, parsing, review, and save.
- Plan listing and outcome reporting.
- An insights dashboard with week, previous-week, and all-time views.

The current interface does not implement a browser microphone flow or suggestion acceptance/rescheduling UI. The backend `/voice` and suggestion endpoints are separate capabilities; the ESP32 firmware does not currently upload audio to `/voice`.

## Requirements

- Node.js and npm.
- The GAP-AI backend running locally or a configured API URL.

## Run locally

From this directory:

```bash
npm install
npm run dev
```

By default, the API client uses `/api`, which the Vite development server proxies to `http://127.0.0.1:8000`. Set `VITE_API_URL` to the backend origin when the proxy is not appropriate. `VITE_*` values are included in browser assets and must not contain secrets.

## Checks

```bash
npm test
npm run build
```

`npm test` runs `tests/*.test.mjs`. The additional `src/api/plans.test.ts` file is not selected by that script, so it is not included in this command's test results.

For the backend API payloads and the implementation status of each route, see [../docs/api-contract.md](../docs/api-contract.md). For hosting instructions, see [../docs/DEPLOY.md](../docs/DEPLOY.md).
