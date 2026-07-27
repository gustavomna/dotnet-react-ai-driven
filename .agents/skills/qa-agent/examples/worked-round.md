# Example — A Worked Round

A full round on **this** repository: React 19 + Vite 8 frontend on `localhost:5173`,
.NET 10 Web API on `localhost:5080`, Vitest for frontend unit tests, Playwright for E2E,
xUnit plus `WebApplicationFactory<Program>` for backend tests.

The round narrates a branch `feat/health-retry` that adds a retry button to the health
indicator. It ends in `FAIL` with two findings: one unit failure and one accessibility
violation.

> **Preconditions.** `vitest-axe` was added to `frontend/package.json` by a human before
> this round, which is what flips the a11y layer to `available`. The agent never installs a
> test framework or an axe package — when they are absent the a11y layer reports
> `skipped-unavailable` and the round says so. See `examples/one-off-audit.md`.

> **Reading the transcripts.** Every `[qa] …` line below is an stderr emission and matches
> one of exactly five shapes: the two run-level lines (`status=starting`,
> `status=finished`), the per-target `status=running` / `status=retrying` lines, the one
> aggregated per-layer result line, and the `status=skipped-unavailable` line. There are no
> other keys. stdout is always JSON.

---

## 0. The change under test

`frontend/src/App.tsx` on `feat/health-retry`, abbreviated to the two lines that matter:

```tsx
// line 47 — the error branch is now gated on a retry counter
{health.kind === "error" && retries >= 3 && (
  <p className="text-sm text-red-600">Backend unreachable: {health.message}</p>
)}

// line 52 — the new retry control
<button onClick={retry} disabled={health.kind === "loading"} className="mt-4 rounded-md border p-2">
  <RefreshCw className="size-4" />
</button>
```

Both defects are real and both are invisible to the existing suite: `App.test.tsx` only
covers the loading and success paths.

---

## 1. Detect the stack

```bash
python3 .agents/skills/qa-agent/scripts/qa.py detect --repo . > qa-stack.json
```

stdout (`qa-stack.json`), trimmed to the fields the rest of the round uses. This is the
real detection for this repository, with the a11y layer available because `vitest-axe` is
now declared in `frontend/package.json`:

```json
{
  "schemaVersion": 1,
  "repo": "/Users/gustavo.araujo/Documents/projects/dotnet-react-ai-driven",
  "detected": true,
  "projects": [
    {"id": "backend", "root": "backend", "language": "csharp", "packageManager": "dotnet",
     "markers": ["backend/Backend.sln"]},
    {"id": "e2e", "root": "e2e", "language": "typescript", "packageManager": "npm",
     "markers": ["e2e/package.json", "e2e/playwright.config.ts"]},
    {"id": "frontend", "root": "frontend", "language": "typescript", "packageManager": "npm",
     "markers": ["frontend/package.json", "frontend/vite.config.ts", "frontend/vitest.config.ts"]}
  ],
  "layers": {
    "unit": {
      "available": true,
      "targets": [
        {"project": "frontend", "runner": "vitest",
         "command": ["npm", "run", "test", "--", "--run"], "cwd": "frontend",
         "testDirs": ["frontend/src/__tests__"],
         "testGlobs": ["**/*.test.ts", "**/*.test.tsx"],
         "reportFormat": "vitest-json",
         "reportFlag": ["--reporter=json", "--outputFile=<REPORT>"],
         "reportEnv": {}},
        {"project": "backend", "runner": "dotnet",
         "command": ["dotnet", "test", "tests/Backend.Api.Tests/Backend.Api.Tests.csproj"],
         "cwd": "backend",
         "testDirs": ["backend/tests/Backend.Api.Tests"],
         "testGlobs": ["**/*Tests.cs"],
         "reportFormat": "trx",
         "reportFlag": ["--logger", "trx;LogFileName=<REPORT>"],
         "reportEnv": {}}
      ],
      "reason": null
    },
    "integration": {
      "available": true,
      "targets": [
        {"project": "backend", "runner": "dotnet",
         "command": ["dotnet", "test", "tests/Backend.Api.Tests/Backend.Api.Tests.csproj"],
         "cwd": "backend",
         "testDirs": ["backend/tests/Backend.Api.Tests"],
         "testGlobs": ["**/*Tests.cs"],
         "reportFormat": "trx",
         "reportFlag": ["--logger", "trx;LogFileName=<REPORT>"],
         "reportEnv": {}}
      ],
      "reason": null
    },
    "e2e": {
      "available": true,
      "targets": [
        {"project": "e2e", "runner": "playwright",
         "command": ["npx", "playwright", "test"], "cwd": "e2e",
         "testDirs": ["e2e"], "testGlobs": ["**/*.spec.ts"],
         "reportFormat": "playwright-json",
         "reportFlag": ["--reporter=json"],
         "reportEnv": {"PLAYWRIGHT_JSON_OUTPUT_NAME": "<REPORT>"}}
      ],
      "reason": null
    },
    "a11y": {
      "available": true,
      "targets": [
        {"project": "frontend", "runner": "vitest",
         "command": ["npm", "run", "test", "--", "--run", "a11y"], "cwd": "frontend",
         "testDirs": ["frontend/src/__tests__"],
         "testGlobs": ["**/*.a11y.*"],
         "reportFormat": "vitest-json",
         "reportFlag": ["--reporter=json", "--outputFile=<REPORT>"],
         "reportEnv": {}}
      ],
      "reason": null
    }
  },
  "conventions": {
    "testFileSuffixes": [".spec.ts", ".test.ts", ".test.tsx", "Tests.cs"],
    "fileNaming": "kebab-case",
    "assertionLibraries": ["fluentassertions", "vitest", "xunit"],
    "e2eFramework": "playwright",
    "componentTestLibrary": "@testing-library/react"
  },
  "runtimes": {
    "node": {"available": true, "version": "24.x", "detail": "v24.11.0"},
    "dotnet": {"available": true, "version": "10.x", "detail": "10.0.100"},
    "headlessBrowser": {"available": true,
      "detail": "playwright CLI at e2e/node_modules/.bin/playwright with browsers cache at ~/Library/Caches/ms-playwright (Version 1.59.1)"}
  },
  "notes": [
    "backend/tests/Backend.Api.Tests/Backend.Api.Tests.csproj serves both the unit and the integration layer (it references Microsoft.AspNetCore.Mvc.Testing); the integration run repeats those tests",
    "a11y targets filter test files by the substring 'a11y'; generated a11y tests must carry it in their file name (for example foo.a11y.test.tsx)"
  ]
}
```

stderr — one line per layer, nothing else:

```
[qa] layer unit: available (dotnet, vitest)
[qa] layer integration: available (dotnet)
[qa] layer e2e: available (playwright)
[qa] layer a11y: available (vitest)
```

Two consequences worth internalising before running anything:

- The **unit layer has two targets** — `frontend` under Vitest and `backend` under
  `dotnet test`. Two targets means two `status=running` lines and still exactly **one**
  aggregated result line for the layer.
- The a11y target is the unit runner plus the literal filter argument `a11y`
  (`npm run test -- --run a11y`). A generated a11y test is only picked up if `a11y` appears
  in its file name — hence `health-indicator.a11y.test.tsx` in section 5.

Without `vitest-axe` the last line would instead read:

```
[qa] layer a11y: unavailable — axe tooling not installed (vitest-axe or jest-axe, @axe-core/playwright)
```

---

## 2. Resolve the scope

```bash
python3 .agents/skills/qa-agent/scripts/qa.py scope --repo . --diff --base main > qa-scope.json
```

```json
{
  "schemaVersion": 1,
  "sources": ["diff"],
  "base": "main",
  "refRange": "main...HEAD",
  "empty": false,
  "files": [
    {"path": "frontend/src/App.tsx", "status": "M", "kind": "source",
     "project": "frontend", "touchesUi": true, "isTest": false},
    {"path": "frontend/src/__tests__/App.test.tsx", "status": "M", "kind": "test",
     "project": "frontend", "touchesUi": false, "isTest": true}
  ],
  "packages": ["frontend"],
  "requirementDocs": [
    "tasks/prd-example-health-check/prd.md",
    "tasks/prd-example-health-check/tasks.md",
    "tasks/prd-example-health-check/techspec.md"
  ],
  "notes": []
}
```

stderr — three lines, always these three:

```
[qa] sources: diff
[qa] files in scope: 2
[qa] packages: frontend
```

The prose the round needs is not in the stream; it is read out of the document. Two facts
drive the rest of the round and both come from `qa-scope.json`, not from stderr:
`frontend/src/App.tsx` has `touchesUi: true`, which makes the a11y layer **required**, and
`frontend/src/__tests__/App.test.tsx` is human-authored, so it will not be overwritten.

---

## 3. Allocate the round and derive the plan

```bash
python3 .agents/skills/qa-agent/scripts/qa.py round new --repo .
```

stdout:

```json
{"schemaVersion": 1, "round": 1, "id": "001", "dir": "qa/rounds/001", "sealed": false}
```

stderr:

```
[qa] allocated round 001 at qa/rounds/001
```

```bash
python3 .agents/skills/qa-agent/scripts/qa.py plan --round 1 \
  --scope qa-scope.json --stack qa-stack.json \
  --requirements tasks/prd-example-health-check/prd.md
```

stderr:

```
[qa] plan written to qa/rounds/001/plan.json and qa/rounds/001/plan.md
[qa] checks: 8 (0 need a layer decision)
```

The script writes the skeleton — the section headings, the discovered conventions, the
scope table and a `TODO` row per candidate. The agent fills in the judgement and deletes
the skeleton's "How to complete this plan" section once nothing is left `TODO`.
Resulting `qa/rounds/001/plan.md`:

```markdown
# QA Plan — Round 001

- Generated: 2026-07-25T14:01:07Z
- Scope: 2 file(s) across frontend
- Ref range: main...HEAD
- Requirement documents: tasks/prd-example-health-check/prd.md
- Available layers: unit, integration, e2e, a11y

## Checks

Each row maps one criterion to one layer. Rows marked `TODO` need the
agent's judgement: pick the layer, name the target, and state the reason.

| ID | Requirement | Layer | Target | Reason | Status |
|---|---|---|---|---|---|
| CHK-001 | FR-4 — "The root page fetches `/api/health` on mount." (prd.md#L35) | unit | frontend/src/App.tsx | observable by stubbing `fetch` and asserting the call; no browser needed | generated |
| CHK-002 | FR-5 — "While the request is in flight, a 'Checking backend health…' message is shown." (prd.md#L36) | unit | frontend/src/App.tsx | a render-state assertion on a pending promise | generated |
| CHK-003 | FR-6 — "On success, the status string is rendered." (prd.md#L37) | unit | frontend/src/App.tsx | already covered by App.test.tsx; extended in a sibling file, not duplicated | existing |
| CHK-004 | FR-7 — "On failure, a human-readable error message is shown with the HTTP status or network error." (prd.md#L38) | unit | frontend/src/App.tsx | a render-state assertion on a rejected promise; no browser needed | generated |
| CHK-005 | UX-1 — "the status region is readable by screen readers; the page uses semantic `main` and `section` elements" (prd.md#L43) | a11y | frontend/src/App.tsx | accessible name and role are only observable on a rendered tree | generated |
| CHK-006 | UX-2 — "renders correctly down to 320 px wide" (prd.md#L44) | e2e | http://localhost:5173/ | needs a real viewport to prove the layout at 320 px | existing |
| CHK-007 | FR-1 — "`GET /api/health` returns `{ \"status\": \"ok\" }` with HTTP 200." (prd.md#L29) | integration | backend/tests/Backend.Api.Tests/HealthEndpointTests.cs | out of scope this round, but the layer runs as regression | existing |
| CHK-008 | UX-3 — "The page is intentionally minimal — one heading, one paragraph, one status line." (prd.md#L42) | — | frontend/src/App.tsx | requires visual judgement; no assertable threshold exists for "minimal" | manual |

## Requirements

| Ref | Text | Source |
|---|---|---|
| FR-1 | `GET /api/health` returns `{ "status": "ok" }` with HTTP 200. | tasks/prd-example-health-check/prd.md#L29 |
| FR-4 | The root page fetches `/api/health` on mount. | tasks/prd-example-health-check/prd.md#L35 |
| FR-5 | While the request is in flight, a "Checking backend health…" message is shown. | tasks/prd-example-health-check/prd.md#L36 |
| FR-6 | On success, the status string is rendered. | tasks/prd-example-health-check/prd.md#L37 |
| FR-7 | On failure, a human-readable error message is shown with the HTTP status or network error. | tasks/prd-example-health-check/prd.md#L38 |
| UX-1 | The status region is readable by screen readers; the page uses semantic `main` and `section` elements. | tasks/prd-example-health-check/prd.md#L43 |
| UX-2 | Renders correctly down to 320 px wide. | tasks/prd-example-health-check/prd.md#L44 |
| UX-3 | The page is intentionally minimal — one heading, one paragraph, one status line. | tasks/prd-example-health-check/prd.md#L42 |

## Test files

| Check | Test file | New or extended | Collision |
|---|---|---|---|
| CHK-001, CHK-002, CHK-004 | frontend/src/__tests__/health-indicator.test.tsx | new | frontend/src/__tests__/App.test.tsx is human-authored — sibling file written instead |
| CHK-005 | frontend/src/__tests__/health-indicator.a11y.test.tsx | new | none; the `a11y` substring is required for the a11y target to select it |

## Manual items

| Check | Requirement | Target | Why it cannot be automated |
|---|---|---|---|
| CHK-008 | UX-3 — "The page is intentionally minimal — one heading, one paragraph, one status line." (prd.md#L42) | frontend/src/App.tsx | requires visual judgement; no assertable threshold exists for "minimal" |

## Scope

| File | Status | Kind | Project | UI |
|---|---|---|---|---|
| `frontend/src/App.tsx` | M | source | frontend | yes |
| `frontend/src/__tests__/App.test.tsx` | M | test | frontend | no |

## Notes

- Coverage: 8 criteria, 7 automated, 1 manual, 0 uncovered.
```

`checklists/plan-review.md` is walked here. Two items caught something:

- **"Does every UI file in scope have at least one a11y check?"** — the first draft had no
  a11y row. CHK-005 was added.
- **"Does the file avoid overwriting a human-authored test?"** — the first draft planned to
  extend `App.test.tsx`. It was retargeted to a sibling file and the collision recorded.

---

## 4. Generated test 1 — unit

`frontend/src/__tests__/health-indicator.test.tsx`

```tsx
/**
 * Requirement: tasks/prd-example-health-check/prd.md
 * Criteria:
 *   FR-4 — "The root page fetches /api/health on mount." (prd.md#L35)
 *   FR-5 — "While the request is in flight, a 'Checking backend health…' message is
 *           shown." (prd.md#L36)
 *   FR-7 — "On failure, a human-readable error message is shown with the HTTP status or
 *           network error." (prd.md#L38)
 * Checks:     CHK-001, CHK-002, CHK-004
 * Layer:      unit — component render only; fetch is stubbed, no browser, no network.
 * Collision:  App.test.tsx is human-authored and was not modified. This is a sibling.
 * Generated by qa-agent, round 001.
 * Verified to fail against main (pre-change tree) before acceptance — see round notes.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../App";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Resolves only when `settle` is called, so the in-flight state is observable. */
function deferredResponse() {
  let settle!: (value: Response) => void;
  const promise = new Promise<Response>((resolve) => {
    settle = resolve;
  });
  return { promise, settle };
}

describe("health indicator", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("requests /api/health once on mount (FR-4)", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/health");
  });

  it("shows the loading message while the request is in flight (FR-5)", async () => {
    const deferred = deferredResponse();
    vi.stubGlobal("fetch", vi.fn(() => deferred.promise));

    render(<App />);

    expect(screen.getByText(/checking backend health/i)).toBeInTheDocument();

    deferred.settle(jsonResponse({ status: "ok" }));
    await waitFor(() => {
      expect(screen.queryByText(/checking backend health/i)).not.toBeInTheDocument();
    });
  });

  it("disables the retry control while the request is in flight (FR-5)", async () => {
    const deferred = deferredResponse();
    vi.stubGlobal("fetch", vi.fn(() => deferred.promise));

    render(<App />);

    expect(screen.getByRole("button", { name: /retry/i })).toBeDisabled();

    deferred.settle(jsonResponse({ status: "ok" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /retry/i })).toBeEnabled();
    });
  });

  it("renders the unreachable message when the health request fails (FR-7)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error: "boom" }, 503)));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/backend unreachable/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/503/)).toBeInTheDocument();
    expect(screen.queryByText(/checking backend health/i)).not.toBeInTheDocument();
  });

  it("re-requests /api/health when retry is pressed (FR-4)", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });
});
```

Determinism notes recorded while walking `checklists/generated-test.md`: no wall clock, no
randomness, no live network, every stub undone in `afterEach`, no fixed sleeps (`waitFor`
throughout), and no secrets — this component needs none.

**Fails for the right reason.** Before acceptance, the file was run against the pre-change
tree in a scratch worktree:

```bash
git worktree add /tmp/qa-prechange main
cp frontend/src/__tests__/health-indicator.test.tsx /tmp/qa-prechange/frontend/src/__tests__/
cd /tmp/qa-prechange/frontend && npm run test -- --run src/__tests__/health-indicator.test.tsx
```

Three tests failed there (`retry` did not exist yet), confirming the file exercises the new
behaviour rather than passing vacuously. The FR-7 test failed for a different reason on the
branch — which is the finding below.

## 5. Generated test 2 — accessibility

`frontend/src/__tests__/health-indicator.a11y.test.tsx`

The file name carries the `a11y` substring on purpose: the detected a11y target is
`npm run test -- --run a11y`, so a scan named anything else would never run.

```tsx
/**
 * Requirement: tasks/prd-example-health-check/prd.md
 * Criterion:  UX-1 — "the status region is readable by screen readers; the page uses
 *             semantic `main` and `section` elements" (prd.md#L43)
 * Check:      CHK-005
 * Layer:      a11y — accessible name and role are only observable on a rendered tree.
 * Tags:       wcag2a, wcag2aa, wcag22aa (WCAG 2.2 Level AA; fixed set, never narrowed)
 * Generated by qa-agent, round 001.
 * Verified to fail against an inverted assertion before acceptance.
 *
 * The raw axe payload is persisted to frontend/qa-axe-health-indicator.json, which matches
 * the "qa-axe-*.json" entry of a11y.resultsGlob. The a11y layer records it in axeArtifacts[] and
 * `report` normalizes it with no flag, so the axe impact -> severity mapping and the
 * incomplete[] -> manualItems mapping are both reached. Without it the round would only
 * know "the a11y layer exited 1".
 *
 * This scan proves what axe can prove. Automated scanning catches roughly a third to a
 * half of real accessibility issues; a clean run is not a compliance claim.
 */
import { writeFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import "vitest-axe/extend-expect";
import { App } from "../App";

const AXE_OPTIONS = {
  runOnly: { type: "tag" as const, values: ["wcag2a", "wcag2aa", "wcag22aa"] },
};

/** Persist the payload where a11y.resultsGlob will find it, then assert on it. */
async function scan(container: Element, name: string) {
  const results = await axe(container, AXE_OPTIONS);
  writeFileSync(`qa-axe-${name}.json`, JSON.stringify(results, null, 2));
  return results;
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("health indicator accessibility (WCAG 2.2 AA)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("has no WCAG 2.2 AA violations in the loading state", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    const { container } = render(<App />);

    expect(await scan(container, "health-indicator-loading")).toHaveNoViolations();
  });

  it("has no WCAG 2.2 AA violations in the success state", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ status: "ok" })));

    const { container } = render(<App />);
    await waitFor(() => expect(screen.getByTestId("health-status")).toBeInTheDocument());

    expect(await scan(container, "health-indicator-success")).toHaveNoViolations();
  });

  it("has no WCAG 2.2 AA violations in the error state", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error: "boom" }, 503)));

    const { container } = render(<App />);
    await waitFor(() => expect(screen.getByRole("button", { name: /retry/i })).toBeEnabled());

    expect(await scan(container, "health-indicator")).toHaveNoViolations();
  });

  it("exposes the status region as a live region with an accessible name", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ status: "ok" })));

    render(<App />);

    const status = await screen.findByRole("status");
    expect(status).toHaveAccessibleName(/backend health/i);
  });

  it("reaches every interactive control by keyboard in DOM order", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ status: "ok" })));

    render(<App />);
    const retry = await screen.findByRole("button", { name: /retry/i });

    await userEvent.tab();

    expect(retry).toHaveFocus();
  });
});
```

Note what this file does **not** contain: no `disableRules`, no `rules: { … enabled: false }`,
no `exclude()`. Those are rejected outright.

---

## 6. Execute

```bash
python3 .agents/skills/qa-agent/scripts/qa.py exec --round 1 \
  --stack qa-stack.json --scope qa-scope.json --plan qa/rounds/001/plan.json
```

stderr, streamed live:

```
[qa] run=20260725-140233 round=001 status=starting layers=unit,integration,e2e,a11y
[qa] layer=unit status=running command="npm run test -- --run" cwd=frontend
[qa] layer=unit status=retrying command="npm run test -- --run src/__tests__/health-indicator.test.tsx -t 'renders\ the\ unreachable\ message\ when\ the\ health\ request\ fails'" cwd=frontend
[qa] layer=unit status=running command="dotnet test tests/Backend.Api.Tests/Backend.Api.Tests.csproj" cwd=backend
[qa] layer=unit status=failed exit=1 duration=37.3s failures=1
[qa] layer=integration status=running command="dotnet test tests/Backend.Api.Tests/Backend.Api.Tests.csproj" cwd=backend
[qa] layer=integration status=passed exit=0 duration=21.4s failures=0
[qa] layer=e2e status=running command="npx playwright test" cwd=e2e
[qa] layer=e2e status=passed exit=0 duration=34.2s failures=0
[qa] layer=a11y status=running command="npm run test -- --run a11y" cwd=frontend
[qa] layer=a11y status=retrying command="npm run test -- --run a11y src/__tests__/health-indicator.a11y.test.tsx -t 'has\ no\ WCAG\ 2\.2\ AA\ violations\ in\ the\ error\ state'" cwd=frontend
[qa] layer=a11y status=failed exit=1 duration=9.9s failures=1
[qa] run=20260725-140233 status=finished verdict=FAIL duration=102.8s
```

Then the human summary, on stderr as well (suppressed by `--json`):

```
[qa] verdict: FAIL
[qa]   layer unit: failed (exit 1, 1 failure(s), 0 flake(s)) -> unit.log
[qa]   layer integration: passed (exit 0, 0 failure(s), 0 flake(s)) -> integration.log
[qa]   layer e2e: passed (exit 0, 0 failure(s), 0 flake(s)) -> e2e.log
[qa]   layer a11y: failed (exit 1, 1 failure(s), 0 flake(s)) -> a11y.log
[qa]   reason: layer unit failed (exit 1, 1 failure(s))
[qa]   reason: layer a11y failed (exit 1, 1 failure(s))
[qa] run directory: qa/rounds/001/runs/20260725-140233
```

Four things to read carefully:

- **The unit layer emitted three lines for two targets.** `frontend` announced itself, failed,
  and announced its targeted retry; then `backend` announced itself and passed. One
  aggregated `status=failed` line closes the layer regardless of target count, and its
  `duration` is the layer's wall time, not any single target's.
- **The retry re-ran only the failed test.** The `-t` value is the leaf test name passed
  through `re.escape`, which is why spaces read as `\ ` and `2.2` as `2\.2` — Vitest takes a
  regex there. It failed again, so the failure is real, not flaky, and the status stays
  `failed` rather than `flaky`. A layer that had recovered would close with
  `status=flaky … flakes=1` instead.
- **A failing layer did not stop the next one.** All four layers ran. That is the point of
  one round reporting every problem.
- **No `exec` line carries a `runId=`, `complete=`, `findings=`, `retried=` or
  `incomplete=` key.** Those do not exist. Run-level lines key on `run=`; layer lines key on
  `layer=` plus `status=`. The only optional suffixes on the aggregated line are ` flakes=N`
  and ` timedOut=true`. (`findings=` does appear later, but on `report`'s single summary
  line, not on anything `exec` writes.)

`qa/rounds/001/runs/20260725-140233/run.json` (abridged — `targets[]`, which holds the
per-attempt argv, is elided):

```json
{
  "schemaVersion": 1,
  "round": 1,
  "runId": "20260725-140233",
  "startedAt": "2026-07-25T14:02:33Z",
  "finishedAt": "2026-07-25T14:04:16Z",
  "repo": "/Users/gustavo.araujo/Documents/projects/dotnet-react-ai-driven",
  "layers": [
    {
      "layer": "unit",
      "status": "failed",
      "exitCode": 1,
      "timedOut": false,
      "retried": true,
      "durationMs": 37300,
      "command": ["npm", "run", "test", "--", "--run",
                  "--reporter=json",
                  "--outputFile=/var/folders/6z/.../T/qa-exec-h492ryrw/qa-report-1.json"],
      "cwd": "frontend",
      "reproduce": "(cd frontend && npm run test -- --run) && (cd backend && dotnet test tests/Backend.Api.Tests/Backend.Api.Tests.csproj)",
      "log": "unit.log",
      "reason": null,
      "failures": [
        {"source": "unit",
         "rule": null,
         "testId": "frontend/src/__tests__/health-indicator.test.tsx::health indicator renders the unreachable message when the health request fails",
         "name": "health indicator renders the unreachable message when the health request fails",
         "file": "frontend/src/App.tsx",
         "line": 47,
         "target": "frontend/src/__tests__/health-indicator.test.tsx::health indicator renders the unreachable message when the health request fails",
         "impact": null,
         "message": "Unable to find an element with the text: /backend unreachable/i",
         "expected": "Backend unreachable: HTTP 503",
         "actual": "Checking backend health…",
         "requirementRef": "FR-7",
         "statedCriterion": true,
         "flaky": false,
         "helpUrl": null,
         "reproduce": "cd frontend && npm run test -- --run src/__tests__/health-indicator.test.tsx -t 'renders the unreachable message when the health request fails'",
         "suggestedFix": null}
      ],
      "flakes": [],
      "env": {"NO_COLOR": "1", "FORCE_COLOR": "0"}
    },
    {"layer": "integration", "status": "passed", "exitCode": 0, "timedOut": false,
     "retried": false, "durationMs": 21400,
     "command": ["dotnet", "test", "tests/Backend.Api.Tests/Backend.Api.Tests.csproj",
                 "--logger", "trx;LogFileName=/var/folders/6z/.../qa-report-1.trx"],
     "cwd": "backend",
     "reproduce": "cd backend && dotnet test tests/Backend.Api.Tests/Backend.Api.Tests.csproj",
     "log": "integration.log", "reason": null, "failures": [], "flakes": [],
     "env": {"NO_COLOR": "1", "FORCE_COLOR": "0"}},
    {"layer": "e2e", "status": "passed", "exitCode": 0, "timedOut": false,
     "retried": false, "durationMs": 34200,
     "command": ["npx", "playwright", "test", "--reporter=json"], "cwd": "e2e",
     "reproduce": "cd e2e && npx playwright test",
     "log": "e2e.log", "reason": null, "failures": [], "flakes": [],
     "env": {"NO_COLOR": "1", "FORCE_COLOR": "0",
             "PLAYWRIGHT_JSON_OUTPUT_NAME": "/var/folders/6z/.../qa-report-1.json"}},
    {
      "layer": "a11y",
      "status": "failed",
      "exitCode": 1,
      "timedOut": false,
      "retried": true,
      "durationMs": 9900,
      "command": ["npm", "run", "test", "--", "--run", "a11y",
                  "--reporter=json",
                  "--outputFile=/var/folders/6z/.../T/qa-exec-h492ryrw/qa-report-1.json"],
      "cwd": "frontend",
      "reproduce": "cd frontend && npm run test -- --run a11y",
      "log": "a11y.log",
      "reason": null,
      "failures": [
        {"source": "a11y",
         "rule": null,
         "testId": "frontend/src/__tests__/health-indicator.a11y.test.tsx::health indicator accessibility (WCAG 2.2 AA) has no WCAG 2.2 AA violations in the error state",
         "name": "health indicator accessibility (WCAG 2.2 AA) has no WCAG 2.2 AA violations in the error state",
         "file": "frontend/src/__tests__/health-indicator.a11y.test.tsx",
         "line": 74,
         "target": "frontend/src/__tests__/health-indicator.a11y.test.tsx::health indicator accessibility (WCAG 2.2 AA) has no WCAG 2.2 AA violations in the error state",
         "impact": null,
         "message": "expect(received).toHaveNoViolations(expected)",
         "expected": null,
         "actual": null,
         "requirementRef": "UX-1",
         "statedCriterion": true,
         "flaky": false,
         "helpUrl": null,
         "reproduce": "cd frontend && npm run test -- --run a11y src/__tests__/health-indicator.a11y.test.tsx -t 'has no WCAG 2.2 AA violations in the error state'",
         "suggestedFix": null}
      ],
      "flakes": [],
      "env": {"NO_COLOR": "1", "FORCE_COLOR": "0"},
      "axeArtifacts": ["frontend/qa-axe-health-indicator.json"]
    }
  ],
  "verdict": "fail",
  "complete": true,
  "skippedLayers": [],
  "runDir": "qa/rounds/001/runs/20260725-140233",
  "verdictReasons": [
    "layer unit failed (exit 1, 1 failure(s))",
    "layer a11y failed (exit 1, 1 failure(s))"
  ],
  "inputs": {
    "stack": "qa-stack.json",
    "scope": "qa-scope.json",
    "plan": "qa/rounds/001/plan.json"
  }
}
```

The a11y layer's own record is deliberately coarse — a Vitest assertion failure with no
rule and no impact. `axeArtifacts[]` is what upgrades it: the next step reads the payload
and replaces that record with the named `button-name` violation at axe impact `critical`.

Exit code `1`.

---

## 7. Report

```bash
python3 .agents/skills/qa-agent/scripts/qa.py report --round 1 --plan qa/rounds/001/plan.json
```

`frontend/qa-axe-health-indicator.json` was recorded in `axeArtifacts[]`, so it is ingested
with no flag. Had the scan written somewhere `a11y.resultsGlob` does not cover, the same
result is reached explicitly — `--axe` is repeatable:

```bash
python3 .agents/skills/qa-agent/scripts/qa.py report --round 1 \
  --plan qa/rounds/001/plan.json --axe frontend/qa-axe-health-indicator.json
```

stderr:

```
[qa] ingested 1 axe violation(s) from 1 payload(s)
[qa] report round=001 run=20260725-140233 verdict="FAIL" findings=2 critical=1 high=1 medium=0 low=0
```

The ingest line is the mechanism that matters. The axe finding **supersedes** the coarse
"a11y layer exited 1" record: same failure, now carrying `rule: button-name`,
`impact: critical` and a help URL, which is what maps it to severity `critical` rather than
to the `medium` default a rule-less runner failure would get.

Two failures, two issue files. Never merged, never batched.

Issue numbers are not emission order — findings are sorted by severity first, then by layer
(`unit` before `integration` before `e2e` before `a11y` before `flake`), then by file and
line, and numbered from there. The `critical` accessibility violation therefore becomes
`issue_001` even though the unit layer failed first.

### `qa/rounds/001/issue_001.md`

```markdown
---
status: open
file: frontend/src/App.tsx
line: 52
severity: critical
author: qa-agent
source: a11y
---

# issue_001 — Retry button has no accessible name, so it is unusable by screen readers

## Failing assertion

`expect(await scan(container, "health-indicator")).toHaveNoViolations()` — axe reported 1
violation of `button-name` (impact: critical) at target `.mt-4`, on the error state of the
health indicator.

## Observed vs expected

| | |
|---|---|
| Expected | No `button-name` violation at `.mt-4`; the retry control announces as "Retry" |
| Observed | The button contains only the `RefreshCw` SVG icon. It has no inner text, no `title`, no `aria-label`, so it announces as "button" with no purpose |

## Reproduce

```bash
cd frontend && npm run test -- --run a11y src/__tests__/health-indicator.a11y.test.tsx -t 'has no WCAG 2.2 AA violations in the error state'
```

## Requirement

`UX-1` — tasks/prd-example-health-check/prd.md — "the status region is readable by screen
readers; the page uses semantic `main` and `section` elements"

`axe: button-name` — https://dequeuniversity.com/rules/axe/4.10/button-name
(WCAG 2.2 SC 4.1.2 Name, Role, Value — Level A)

## Suggested fix

`App.tsx:52` renders an icon-only button. Add `aria-label="Retry"` to the `<button>` and
`aria-hidden="true"` to the `RefreshCw` icon so the icon is not announced separately:

```tsx
<button onClick={retry} disabled={health.kind === "loading"} aria-label="Retry" className="mt-4 rounded-md border p-2">
  <RefreshCw className="size-4" aria-hidden="true" />
</button>
```

Do not resolve this by excluding the selector or disabling the `button-name` rule — both
are refused, and a rule-scoped a11y suppression is always rejected.
```

`severity: critical` is mechanical: axe impact `critical` maps to severity `critical`,
`serious` to `high`, `moderate` to `medium`, `minor` to `low`. That mapping is only
reachable because the payload was ingested; without it this would have been filed as a
rule-less `medium`.

### `qa/rounds/001/issue_002.md`

```markdown
---
status: open
file: frontend/src/App.tsx
line: 47
severity: high
author: qa-agent
source: unit
---

# issue_002 — Backend error message is never rendered on the first failed health request

## Failing assertion

`expect(screen.getByText(/backend unreachable/i)).toBeInTheDocument()` — element not
found. Testing Library reported: "Unable to find an element with the text:
/backend unreachable/i".

## Observed vs expected

| | |
|---|---|
| Expected | After `/api/health` responds 503, the page shows "Backend unreachable: HTTP 503" |
| Observed | The loading message "Checking backend health…" stays mounted; no error text is ever rendered on the first failure |

## Reproduce

```bash
cd frontend && npm run test -- --run src/__tests__/health-indicator.test.tsx -t 'renders the unreachable message when the health request fails'
```

## Requirement

`FR-7` — tasks/prd-example-health-check/prd.md — "On failure, a human-readable error
message is shown with the HTTP status or network error."

## Suggested fix

`App.tsx:47` gates the error branch on `health.kind === "error" && retries >= 3`, so the
message only appears after the third attempt, while the loading paragraph has no
corresponding exit condition. The retry counter governs whether to retry, not whether to
inform the user. Render the error branch on `health.kind === "error"` alone and let
`retries` drive only the automatic re-request.
```

`severity: high` is not a judgement call either: FR-7 is a **stated** acceptance criterion
in the plan, and a failing test of a stated criterion is `high` at minimum.

---

## 8. Verdict

```bash
python3 .agents/skills/qa-agent/scripts/qa.py verdict --round 1
```

stdout:

```json
{
  "schemaVersion": 1,
  "round": 1,
  "runId": "20260725-140233",
  "verdict": "fail",
  "rawVerdict": "fail",
  "verdictAdjusted": false,
  "complete": true,
  "reasons": [
    "layer=unit exited 1 with 1 failure(s)",
    "layer=a11y exited 1 with 1 failure(s)",
    "verdict read from the sealed summary.json of round 001"
  ],
  "skippedLayers": []
}
```

stderr:

```
[qa] verdict round=001 verdict="FAIL"
```

Exit code `1`.

`qa/rounds/001/summary.md`, which `report` also echoes to stderr in full:

```markdown
# QA round 001 - summary

**Verdict: FAIL**

Run `20260725-140233` - generated 2026-07-25T14:04:18Z - artifacts in `qa/rounds/001`

## Findings by severity

| severity | count |
|---|---|
| critical | 1 |
| high | 1 |
| medium | 0 |
| low | 0 |
| **total** | **2** |

## Issues

1. `issue_001` - **critical** - a11y - `frontend/src/App.tsx:52` - Retry button has no accessible name, so it is unusable by screen readers
2. `issue_002` - **high** - unit - `frontend/src/App.tsx:47` - Backend error message is never rendered on the first failed health request

## Why this verdict

- layer=unit exited 1 with 1 failure(s)
- layer=a11y exited 1 with 1 failure(s)

## Layers

| layer | status | exit | reproduce |
|---|---|---|---|
| unit | failed | 1 | `(cd frontend && npm run test -- --run) && (cd backend && dotnet test tests/Backend.Api.Tests/Backend.Api.Tests.csproj)` |
| integration | passed | 0 | `cd backend && dotnet test tests/Backend.Api.Tests/Backend.Api.Tests.csproj` |
| e2e | passed | 0 | `cd e2e && npx playwright test` |
| a11y | failed | 1 | `cd frontend && npm run test -- --run a11y` |

## Manual items

- UX-3 frontend/src/App.tsx - requires visual judgement; no assertable threshold exists for "minimal"

## Coverage, baseline, suppressions

- Criteria: 8 total, 7 automated, 1 manual, 0 uncovered.
- Baseline: not used (0 pre-existing, 2 introduced).
- Suppressions: 0 valid, 0 invalid, 0 expired. An invalid or expired suppression never silences a check.

## Notes

- Automated accessibility scanning catches roughly a third to a half of real issues. A clean a11y layer is evidence, not proof of conformance.
- The only permitted response to a failure is an issue file. Deleting or skipping a test, disabling a rule, widening a tolerance, or broadening an exclusion is forbidden.
```

`qa/rounds/001/summary.json`, the machine gate:

```json
{
  "schemaVersion": 1,
  "round": 1,
  "runId": "20260725-140233",
  "verdict": "fail",
  "rawVerdict": "fail",
  "verdictAdjusted": false,
  "reasons": [
    "layer=unit exited 1 with 1 failure(s)",
    "layer=a11y exited 1 with 1 failure(s)"
  ],
  "complete": true,
  "generatedAt": "2026-07-25T14:04:18Z",
  "layers": [
    {"layer": "unit", "status": "failed", "exitCode": 1,
     "reproduce": "(cd frontend && npm run test -- --run) && (cd backend && dotnet test tests/Backend.Api.Tests/Backend.Api.Tests.csproj)"},
    {"layer": "integration", "status": "passed", "exitCode": 0,
     "reproduce": "cd backend && dotnet test tests/Backend.Api.Tests/Backend.Api.Tests.csproj"},
    {"layer": "e2e", "status": "passed", "exitCode": 0,
     "reproduce": "cd e2e && npx playwright test"},
    {"layer": "a11y", "status": "failed", "exitCode": 1,
     "reproduce": "cd frontend && npm run test -- --run a11y"}
  ],
  "counts": {"critical": 1, "high": 1, "medium": 0, "low": 0, "total": 2},
  "issues": [
    {"id": "issue_001", "file": "frontend/src/App.tsx", "line": 52, "severity": "critical",
     "source": "a11y", "status": "open",
     "title": "Retry button has no accessible name, so it is unusable by screen readers"},
    {"id": "issue_002", "file": "frontend/src/App.tsx", "line": 47, "severity": "high",
     "source": "unit", "status": "open",
     "title": "Backend error message is never rendered on the first failed health request"}
  ],
  "manualItems": [
    {"criterion": "UX-3 frontend/src/App.tsx",
     "reason": "requires visual judgement; no assertable threshold exists for \"minimal\""}
  ],
  "suppressions": {"valid": 0, "invalid": 0, "expired": 0},
  "baseline": {"used": false, "preexisting": 0, "introduced": 2},
  "skippedLayers": [],
  "coverage": {"criteria": 8, "automated": 7, "manual": 1, "uncovered": 0}
}
```

Writing `summary.json` seals round 001. Fixing the two findings and re-running allocates
round 002; round 001 is never edited.

---

## What the agent did not do

- It did not delete, skip, or loosen the FR-7 test to make the unit layer green.
- It did not exclude `.mt-4` or disable the `button-name` rule to make the a11y layer
  green. A rule-scoped a11y suppression is always rejected.
- It did not touch `frontend/src/__tests__/App.test.tsx`, which is human-authored.
- It did not stage or commit the two generated test files — `generation.autoStage`
  defaults to `false`, and committing is the developer's decision.
- It did not claim the interface is accessible. It reported what axe could prove.
