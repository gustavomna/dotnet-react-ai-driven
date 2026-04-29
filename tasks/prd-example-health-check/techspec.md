# Tech Spec — Backend Health Check

## Executive Summary

Expose `GET /api/health` from the .NET 10 Web API as a minimal-API route that returns a JSON `{ status: "ok" }` payload. In the frontend, fetch the endpoint via the Vite dev-server proxy on `App` mount and render the returned status. The single xUnit integration test hits the endpoint through `WebApplicationFactory<Program>`; the single Playwright smoke test verifies the full loop in a real browser. Both layers stay deliberately small so the AI workflow has an honest walking skeleton to extend.

## System Architecture

### Component Overview

- **`backend/src/Backend.Api/Program.cs`** — minimal-API host; registers the `/api/health` route inline.
- **`HealthResponse`** record (in `Program.cs`) — request/response DTO, colocated because the feature is a single endpoint.
- **`frontend/src/App.tsx`** — React component that owns the health state and the `fetch` call.
- **`frontend/vite.config.ts`** — declares the `/api` → `http://localhost:5080` proxy that makes the frontend fetch work without CORS.
- **`backend/tests/Backend.Api.Tests/HealthEndpointTests.cs`** — integration test using `WebApplicationFactory<Program>`.
- **`frontend/src/__tests__/App.test.tsx`** — unit test using Vitest + Testing Library with a stubbed `fetch`.
- **`e2e/app.spec.ts`** + **`playwright.config.ts`** — browser smoke test exercising both servers.

## Implementation Design

### Key Interfaces

```csharp
public record HealthResponse(string Status);

app.MapGet("/api/health", () => Results.Ok(new HealthResponse("ok")));
```

```ts
type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; status: string }
  | { kind: "error"; message: string };
```

### Data Models

- `HealthResponse { Status: string }` — single field, serialized camelCase by default ASP.NET Core JSON options.

### API Endpoints

- `GET /api/health` — returns `200 OK` with `{ "status": "ok" }`. No parameters, no auth, no headers required.

## Integration Points

None. Feature is self-contained.

## Testing Approach

### Unit Tests

- `frontend/src/__tests__/App.test.tsx` — stubs `fetch` globally, renders `<App />`, asserts the loading message then the rendered status.

### Integration Tests

- `backend/tests/Backend.Api.Tests/HealthEndpointTests.cs` — spins up the full ASP.NET pipeline via `WebApplicationFactory<Program>`, issues a real HTTP `GET /api/health`, asserts status code and body.

### E2E Tests

- `e2e/app.spec.ts` — Playwright launches Chromium, hits `http://localhost:5173`, asserts the heading and the health status text. Playwright's `webServer` config boots both the backend and frontend automatically.

## Development Sequencing

### Build Order

1. Backend endpoint + integration test (provable without a frontend).
2. Frontend component + unit test (provable in isolation with a stubbed `fetch`).
3. Playwright config + smoke test (integrates both).

### Technical Dependencies

- .NET 10 SDK, Node 20+, npm. No external services.

## Observability

Not applicable at this scale. Add structured logging only when real features ship.

## Technical Considerations

### Key Decisions

- **Minimal API over a full Controller class** — one endpoint with no business logic doesn't need the controller/service split promised by `CLAUDE.md` for real features. Document this decision so the pattern scales up when the next feature needs a service.
- **HTTP only in dev (port 5080)** — skips the dev-cert dance that blocks new users on macOS/Linux. Production concerns are out of scope.
- **Route-level DTO colocation** — `HealthResponse` lives in `Program.cs` because it is consumed only by this one route. Extract on second use.

### Known Risks

- If a future feature adds auth middleware, `/api/health` must remain anonymous. Tag it with `.AllowAnonymous()` explicitly once auth exists.

### Standard Skills Compliance

- `dotnet-best-practices` — for the .NET minimal API structure.
- `vercel-react-best-practices` — for the React component.
- `executar-task`, `executar-review` — workflow skills.

### Relevant and Dependent Files

- `backend/src/Backend.Api/Program.cs`
- `backend/tests/Backend.Api.Tests/HealthEndpointTests.cs`
- `frontend/src/App.tsx`
- `frontend/vite.config.ts`
- `frontend/src/__tests__/App.test.tsx`
- `playwright.config.ts`
- `e2e/app.spec.ts`
