# Task 1.0: Backend health endpoint + frontend indicator + tests

<critical>Read the prd.md and techspec.md files in this folder — if you don't read these files your task will be invalidated</critical>

## Overview

Ship the walking-skeleton health check end-to-end: a `GET /api/health` endpoint, a frontend indicator that fetches it through the Vite proxy, and one test at each layer.

<skills>
### Standard Skills Compliance

- `executar-task` — workflow skill for task execution.
- `dotnet-best-practices` — for the .NET minimal API.
- `vercel-react-best-practices` — for the React component state handling.
- `task-review` — triggered at the end by the `task-reviewer` agent.
</skills>

<requirements>
- `GET /api/health` must return HTTP 200 with body `{ "status": "ok" }`.
- Frontend `App` must render three distinct states: loading, ok, error.
- Vite proxy `/api` → `http://localhost:5080` must be configured in `vite.config.ts`.
- Tests: one xUnit integration test, one Vitest unit test, one Playwright smoke test.
- All three test commands must pass: `dotnet test`, `npm run test`, `npx playwright test`.
</requirements>

## Subtasks

- [x] 1.1 Add `/api/health` route to `backend/src/Backend.Api/Program.cs` with a `HealthResponse` record.
- [x] 1.2 Write `HealthEndpointTests` using `WebApplicationFactory<Program>`.
- [x] 1.3 Build `App.tsx` with a `HealthState` discriminated union covering loading/ok/error.
- [x] 1.4 Configure `server.proxy` in `vite.config.ts` for `/api`.
- [x] 1.5 Write `App.test.tsx` with a stubbed `fetch`.
- [x] 1.6 Configure `playwright.config.ts` at the repo root with a `webServer` array that starts both servers.
- [x] 1.7 Write `e2e/app.spec.ts` smoke test.

## Implementation Details

See `techspec.md` for key interfaces, data models, and the development sequence. Do not duplicate the spec here — reference it.

## Success Criteria

- Manual check: `curl localhost:5080/api/health` returns `{"status":"ok"}`.
- Manual check: opening `http://localhost:5173` shows the backend status rendered in the UI.
- `cd frontend && npm run lint && npm run typecheck && npm run build && npm run test` — all green.
- `cd backend && dotnet build && dotnet test` — all green.
- `npx playwright test` — smoke test passes.

## Task Tests

- [x] Unit tests (frontend Vitest, stubbed fetch).
- [x] Integration tests (backend xUnit via `WebApplicationFactory`).
- [x] E2E tests (Playwright Chromium).

<critical>ALWAYS CREATE AND RUN THE TASK TESTS BEFORE CONSIDERING IT FINISHED</critical>

## Relevant Files

- `backend/src/Backend.Api/Program.cs`
- `backend/tests/Backend.Api.Tests/HealthEndpointTests.cs`
- `frontend/src/App.tsx`
- `frontend/vite.config.ts`
- `frontend/src/__tests__/App.test.tsx`
- `playwright.config.ts`
- `e2e/app.spec.ts`
