# PRD — Backend Health Check

## Overview

This feature gives developers and automated tooling a single, reliable endpoint to confirm that the backend is running and reachable from the frontend. It is the first feature every project needs and serves as the canonical "walking skeleton" for the AI-driven workflow in this template.

## Objectives

- A developer cloning the repo can confirm the backend is up within seconds (no docs hunting).
- The frontend visually proves end-to-end connectivity — including the Vite proxy — on first load.
- The feature exercises every stage of the AI workflow (PRD → Tech Spec → Tasks → Implementation → Review → QA → Bugfix) so new users have a reference.

Success metrics:

- `curl http://localhost:5080/api/health` returns HTTP 200 with `{"status":"ok"}` within 100 ms on a cold start.
- The frontend at `http://localhost:5173` renders the status string fetched through the proxy.
- One Playwright smoke test passes against both servers.

## User Stories

- As a **developer onboarding the template**, I want to open the frontend and see the backend status so that I know the stack is wired correctly before I write a line of code.
- As an **AI agent implementing a new feature**, I want a minimal existing endpoint and test pair to copy so that I stay consistent with the project's patterns.
- As a **CI pipeline**, I want a stable health endpoint so that I can gate deploys on backend readiness.

## Core Features

### Health endpoint

1. `GET /api/health` returns `{ "status": "ok" }` with HTTP 200.
2. The endpoint is anonymous — no auth required.
3. The endpoint is registered in `Program.cs` with no supporting service (it's trivial; a service would be over-engineering).

### Frontend health indicator

1. The root page fetches `/api/health` on mount.
2. While the request is in flight, a "Checking backend health…" message is shown.
3. On success, the status string is rendered.
4. On failure, a human-readable error message is shown with the HTTP status or network error.

## User Experience

- The page is intentionally minimal — one heading, one paragraph, one status line.
- Accessible: the status region is readable by screen readers; the page uses semantic `main` and `section` elements.
- Responsive: renders correctly down to 320 px wide.

## High-Level Technical Constraints

- Must work with the existing stack: React 19 + Vite 8 frontend, .NET 10 Web API backend.
- Frontend runs on `localhost:5173`, backend on `localhost:5080` — Vite proxy bridges `/api/*`.
- No database, no auth, no external services.

## Out of Scope

- Liveness vs. readiness distinction (not needed until deployments exist).
- Detailed health checks (DB connectivity, downstream services) — future tech-debt item once those dependencies exist.
- Authentication on the endpoint.
