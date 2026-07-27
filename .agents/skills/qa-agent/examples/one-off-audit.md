# Example — One-Off Audit of an Unfamiliar Repository

The third invocation context from the PRD: pointed at a repository the agent did not write,
with no prior configuration. It detects the stack, runs **read-only** checks, scans for
accessibility violations, and reports findings **without generating or committing tests**.

The subject here is `~/audits/acme-portal` — a React 19 + Vite frontend on `localhost:5173`
and a .NET 10 Web API on `localhost:5080`, cloned an hour ago. No `qa/` directory, no
`qa.config.json`, no requirement documents.

> **Reading the transcripts.** Every `[qa] …` line is an stderr emission. `detect` prints
> exactly one line per layer, `scope` prints exactly three lines, and `exec` prints only the
> two run-level lines, a `status=running` (and possibly `status=retrying`) line **per
> target**, one aggregated result line **per layer**, and `status=skipped-unavailable` for a
> layer it cannot run. There is no `runId=`, `complete=`, `findings=`, `retried=` or
> `incomplete=` key anywhere. stdout is always JSON.

---

## 0. Keep the audited repository pristine

An audit writes nothing into a repository it does not own. Point the output directory
somewhere outside it with the global `--qa-dir` flag, and repeat that flag on every
invocation:

```bash
export AUDIT=~/audits/acme-portal
export AUDIT_QA=/tmp/audit-acme/qa
```

Everything below carries `--repo "$AUDIT" --qa-dir "$AUDIT_QA"`. The repository's working
tree stays byte-identical from start to finish.

Note that JSON documents are captured with shell redirection, not with `--out`: `--out`
refuses to write outside the repository root, which is exactly the property that makes an
audit safe.

---

## 1. Detect, and say what will happen before anything happens

```bash
python3 .agents/skills/qa-agent/scripts/qa.py detect --repo "$AUDIT" --qa-dir "$AUDIT_QA" > /tmp/audit-acme/stack.json
```

```json
{
  "schemaVersion": 1,
  "repo": "/Users/gustavo.araujo/audits/acme-portal",
  "detected": true,
  "projects": [
    {"id": "api", "root": "api", "language": "csharp", "packageManager": "dotnet",
     "markers": ["api/Acme.Portal.sln"]},
    {"id": "e2e", "root": "e2e", "language": "typescript", "packageManager": "npm",
     "markers": ["e2e/package.json", "e2e/playwright.config.ts"]},
    {"id": "web", "root": "web", "language": "typescript", "packageManager": "npm",
     "markers": ["web/package.json", "web/vite.config.ts"]}
  ],
  "layers": {
    "unit": {"available": true, "targets": [
      {"project": "web", "runner": "vitest",
       "command": ["npm", "run", "test", "--", "--run"], "cwd": "web",
       "testDirs": ["web/src/__tests__"], "testGlobs": ["**/*.test.ts", "**/*.test.tsx"],
       "reportFormat": "vitest-json", "reportFlag": ["--reporter=json", "--outputFile=<REPORT>"],
       "reportEnv": {}},
      {"project": "api", "runner": "dotnet",
       "command": ["dotnet", "test", "tests/Acme.Portal.Tests/Acme.Portal.Tests.csproj"],
       "cwd": "api", "testDirs": ["api/tests/Acme.Portal.Tests"], "testGlobs": ["**/*Tests.cs"],
       "reportFormat": "trx", "reportFlag": ["--logger", "trx;LogFileName=<REPORT>"],
       "reportEnv": {}}
    ], "reason": null},
    "integration": {"available": false, "targets": [],
      "reason": "no integration test target detected"},
    "e2e": {"available": true, "targets": [
      {"project": "e2e", "runner": "playwright",
       "command": ["npx", "playwright", "test"], "cwd": "e2e",
       "testDirs": ["e2e"], "testGlobs": ["**/*.spec.ts"],
       "reportFormat": "playwright-json", "reportFlag": ["--reporter=json"],
       "reportEnv": {"PLAYWRIGHT_JSON_OUTPUT_NAME": "<REPORT>"}}
    ], "reason": null},
    "a11y": {"available": true, "targets": [
      {"project": "e2e", "runner": "playwright",
       "command": ["npx", "playwright", "test", "a11y"], "cwd": "e2e",
       "testDirs": ["e2e"], "testGlobs": ["**/*.a11y.*"],
       "reportFormat": "playwright-json", "reportFlag": ["--reporter=json"],
       "reportEnv": {"PLAYWRIGHT_JSON_OUTPUT_NAME": "<REPORT>"}}
    ], "reason": null}
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
    "a11y targets filter test files by the substring 'a11y'; generated a11y tests must carry it in their file name (for example foo.a11y.test.tsx)"
  ]
}
```

stderr — one line per layer, and nothing else:

```
[qa] layer unit: available (dotnet, vitest)
[qa] layer integration: unavailable — no integration test target detected
[qa] layer e2e: available (playwright)
[qa] layer a11y: available (playwright)
```

Read the a11y line carefully. It says `available (playwright)` because
`@axe-core/playwright` is declared **and** there is a Playwright target to host the scan.
The a11y target is that target plus the literal filter argument `a11y`, so the repository's
`e2e/routes.a11y.spec.ts` is what will run. A scan file without `a11y` in its name would
never be selected.

The layer report is terse by design; the agent, not the script, is responsible for saying
what it is about to do before it does it. Its own pre-flight summary — plain prose, not a
`[qa]` emission:

```
First run in /Users/gustavo.araujo/audits/acme-portal — audit mode, read only

Detected
  web       React 19 + Vite, vitest, @testing-library/react
  api       .NET 10, xunit, FluentAssertions
  e2e       playwright + @axe-core/playwright, chromium installed

Layers
  unit          available   (web via vitest, api via dotnet test — one layer, two targets)
  integration   unavailable (no integration test target detected)
  e2e           available   (playwright, 14 specs)
  a11y          available   (e2e/routes.a11y.spec.ts, @axe-core/playwright)

Configuration
  none found — using defaults derived from the detected stack

Requirements
  none found — the plan will be inference-based

Will write
  /tmp/audit-acme/qa/rounds/001/**    (plan, summary, issue files, run logs)

Will NOT write
  anything inside /Users/gustavo.araujo/audits/acme-portal
  no generated tests, no staged changes, no commits

Proceed? [y/N]
```

---

## 2. Scope the whole repository

There is no branch to diff against in an audit — the subject is the repository as it
stands:

```bash
python3 .agents/skills/qa-agent/scripts/qa.py scope --repo "$AUDIT" --qa-dir "$AUDIT_QA" --path . > /tmp/audit-acme/scope.json
```

```json
{
  "schemaVersion": 1,
  "sources": ["path"],
  "base": "main",
  "refRange": "main...HEAD",
  "empty": false,
  "files": ["… 412 entries elided …"],
  "packages": ["api", "e2e", "web"],
  "requirementDocs": [],
  "notes": [
    "no requirement artifact found; the plan will be inference-based"
  ]
}
```

stderr — exactly three lines, always these three:

```
[qa] sources: path
[qa] files in scope: 412
[qa] packages: api, e2e, web
```

The source label is `path`, singular, and `base`/`refRange` are still resolved even though
the scope did not come from a diff — they record which branch the working tree sits on, not
what was selected. The two facts the audit needs are in the document, not the stream: 184
entries carry `touchesUi: true`, which makes the a11y layer required, and `requirementDocs`
is empty, which makes the plan inference-based.

---

## 3. An inference-based, read-only plan

```bash
python3 .agents/skills/qa-agent/scripts/qa.py round new --repo "$AUDIT" --qa-dir "$AUDIT_QA"
python3 .agents/skills/qa-agent/scripts/qa.py plan --round 1 --repo "$AUDIT" --qa-dir "$AUDIT_QA" \
  --scope /tmp/audit-acme/scope.json --stack /tmp/audit-acme/stack.json
```

stderr from the two commands:

```
[qa] allocated round 001 at ../../../../tmp/audit-acme/qa/rounds/001
[qa] plan written to ../../../../tmp/audit-acme/qa/rounds/001/plan.json and ../../../../tmp/audit-acme/qa/rounds/001/plan.md
[qa] checks: 5 (0 need a layer decision)
[qa] plan is INFERENCE-BASED: no requirement artifact was found
```

Paths in the stream are printed relative to the repository root, which is why an
out-of-tree `--qa-dir` renders with `../` segments. The absolute location is unchanged.

`/tmp/audit-acme/qa/rounds/001/plan.md` opens with the honesty banner the script emits as
its first line, before the heading:

```markdown
> INFERENCE-BASED PLAN — no requirement artifact was found, so expected behaviour is inferred from the diff and the public interfaces it touches.

# QA Plan — Round 001

- Generated: 2026-07-25T16:10:44Z
- Scope: 412 file(s) across api, e2e, web
- Ref range: main...HEAD
- Requirement documents: none found
- Available layers: unit, e2e, a11y
- Layer `integration` unavailable: no integration test target detected

## Checks

Each row maps one criterion to one layer. Rows marked `TODO` need the
agent's judgement: pick the layer, name the target, and state the reason.

| ID | Requirement | Layer | Target | Reason | Status |
|---|---|---|---|---|---|
| CHK-001 | inferred — the existing vitest suite states the web app's expected behaviour | unit | web/src/__tests__ | run as-is; the suite is the repository's own claim about itself | existing |
| CHK-002 | inferred — the existing xunit suite states the API's expected behaviour | unit | api/tests/Acme.Portal.Tests | run as-is; same layer as CHK-001, second target | existing |
| CHK-003 | inferred — the existing playwright suite states the primary user flows | e2e | e2e/*.spec.ts | run as-is | existing |
| CHK-004 | inferred — WCAG 2.2 AA on every route reachable from `/` | a11y | e2e/routes.a11y.spec.ts | the repository already scans with @axe-core/playwright; the scan is run unchanged | existing |
| CHK-005 | inferred — request/response contract of `/api/*` | integration | /api/* | layer unavailable: no integration test target detected | manual |

## Requirements

No stated requirement was found. Expected behaviour is inferred from the
diff and the public interfaces it touches; every verdict below inherits
that uncertainty.

## Manual items

| Check | Target | Why it cannot be automated |
|---|---|---|
| CHK-005 | /api/* | no integration test target exists in this repository; adding one is a human decision |

Anything axe reports as `incomplete[]` is added here by `report`, after the scan has run.

## Notes

- Audit mode: every row is `existing` or `manual`; no row is `planned` or `generated`.
```

Every row is `existing` or `manual`. **No row is `planned` or `generated`** — an audit does
not write tests unless the owner asks for them.

---

## 4. Run the existing checks, unchanged

```bash
python3 .agents/skills/qa-agent/scripts/qa.py exec --round 1 --repo "$AUDIT" --qa-dir "$AUDIT_QA" \
  --stack /tmp/audit-acme/stack.json --scope /tmp/audit-acme/scope.json \
  --plan /tmp/audit-acme/qa/rounds/001/plan.json
```

```
[qa] run=20260725-161104 round=001 status=starting layers=unit,integration,e2e,a11y
[qa] layer=unit status=running command="npm run test -- --run" cwd=web
[qa] layer=unit status=retrying command="npm run test -- --run src/__tests__/invoice-total.test.ts -t 'rounds\ to\ two\ decimal\ places'" cwd=web
[qa] layer=unit status=running command="dotnet test tests/Acme.Portal.Tests/Acme.Portal.Tests.csproj" cwd=api
[qa] layer=unit status=failed exit=1 duration=104.3s failures=1
[qa] layer=integration status=skipped-unavailable reason="no integration test target detected"
[qa] layer=e2e status=running command="npx playwright test" cwd=e2e
[qa] layer=e2e status=retrying command="npx playwright test --last-failed" cwd=e2e
[qa] layer=e2e status=flaky exit=0 duration=108.3s failures=0 flakes=1
[qa] layer=a11y status=running command="npx playwright test a11y" cwd=e2e
[qa] layer=a11y status=retrying command="npx playwright test a11y --last-failed" cwd=e2e
[qa] layer=a11y status=failed exit=1 duration=54.9s failures=3
[qa] run=20260725-161104 status=finished verdict=FAIL duration=267.5s
```

Then the human summary, on stderr as well (suppressed by `--json`):

```
[qa] verdict: FAIL
[qa]   layer unit: failed (exit 1, 1 failure(s), 0 flake(s)) -> unit.log
[qa]   layer integration: skipped-unavailable (exit None, 0 failure(s), 0 flake(s)) -> integration.log
[qa]   layer e2e: flaky (exit 0, 0 failure(s), 1 flake(s)) -> e2e.log
[qa]   layer a11y: failed (exit 1, 3 failure(s), 0 flake(s)) -> a11y.log
[qa]   reason: layer unit failed (exit 1, 1 failure(s))
[qa]   reason: layer a11y failed (exit 1, 3 failure(s))
[qa] run directory: ../../../../tmp/audit-acme/qa/rounds/001/runs/20260725-161104
```

Five things to read carefully in that output:

- **The unit layer emitted three lines for two targets and closed once.** `web` announced
  itself, failed, and announced its targeted retry; then `api` announced itself and passed.
  One aggregated `status=failed` line closes the layer. Its `exit` is the first non-zero
  exit among the targets and its `duration` is the layer's wall time, not either target's.
- **The integration layer was skipped, not passed.** `status=skipped-unavailable` with a
  quoted reason and no `exit`/`duration`/`failures` keys at all. `complete` becomes `false`
  and the verdict line will carry the qualifier.
- **The e2e layer is `flaky`, not `passed`.** It failed, passed on `--last-failed`, and
  closed as `flaky` with `flakes=1`. The `flakes=` suffix appears only on a flaky layer;
  the only other optional suffix is `timedOut=true`. A passing retry never erases the
  failure.
- **The a11y layer reported three failures, and that is all the layer itself knows.** The
  count of axe `incomplete[]` results is not in the stream — there is no `incomplete=` key.
  Incomplete results reach the report through the axe payload, in the next step.
- **A failing layer did not stop the next one.** All four layers were visited in one round.

---

## 5. Findings, reported and not fixed

The Playwright scan wrote its raw axe payloads as
`e2e/test-results/qa-axe-settings.json` and `e2e/test-results/qa-axe-dashboard.json`. Those
match the `**/qa-axe-*.json` entry of `a11y.resultsGlob` (default
`["test-results/**/axe-*.json", "**/qa-axe-*.json", "**/axe-results*.json"]`, every pattern
resolved from the **repository root**), so the a11y layer recorded them in `axeArtifacts[]`
and `report` ingests them with no flag:

```bash
python3 .agents/skills/qa-agent/scripts/qa.py report --round 1 --repo "$AUDIT" --qa-dir "$AUDIT_QA" --author auditor
```

Watch the anchoring: `test-results/**/axe-*.json` only matches a `test-results/` directory
at the repository root, which a Playwright project nested in `e2e/` does not produce. Had
the payloads landed somewhere no pattern covers, the same result is reached explicitly —
`--axe` is repeatable and takes a path:

```bash
python3 .agents/skills/qa-agent/scripts/qa.py report --round 1 --repo "$AUDIT" --qa-dir "$AUDIT_QA" \
  --author auditor \
  --axe e2e/test-results/qa-axe-settings.json --axe e2e/test-results/qa-axe-dashboard.json
```

stderr:

```
[qa] ingested 3 axe violation(s) from 2 payload(s)
[qa] report round=001 run=20260725-161104 verdict="FAIL — INCOMPLETE (integration: skipped-unavailable)" findings=5 critical=1 high=1 medium=3 low=0
```

The ingest line is what makes the severities meaningful. Axe findings **supersede** the
coarse "a11y layer exited 1" record: each violating node becomes its own finding carrying
its rule id, its impact and its help URL, which is how an axe `critical` is filed as
severity `critical` instead of as the rule-less `medium` a bare runner failure would get.
The same pass turns every `incomplete[]` entry into a `manualItems` row.

`report` then echoes `summary.md` in full to stderr:

```markdown
# QA round 001 - summary

**Verdict: FAIL — INCOMPLETE (integration: skipped-unavailable)**

Run `20260725-161104` - generated 2026-07-25T16:15:44Z - artifacts in `../../../../tmp/audit-acme/qa/rounds/001`

## Findings by severity

| severity | count |
|---|---|
| critical | 1 |
| high | 1 |
| medium | 3 |
| low | 0 |
| **total** | **5** |

## Issues

1. `issue_001` - **critical** - a11y - `http://localhost:5173/settings` - label: Form elements must have labels
2. `issue_002` - **high** - a11y - `http://localhost:5173/` - color-contrast: Elements must meet minimum color contrast ratio thresholds
3. `issue_003` - **medium** - unit - `web/src/lib/invoice-total.ts:14` - invoice total rounds to two decimal places
4. `issue_004` - **medium** - a11y - `http://localhost:5173/dashboard` - region: All page content should be contained by landmarks
5. `issue_005` - **medium** - flake - `e2e/checkout.spec.ts:42` - Flaky test: checkout completes an order with a saved card

## Why this verdict

- layer=unit exited 1 with 1 failure(s)
- layer=a11y exited 1 with 3 failure(s)
- layer=integration skipped-unavailable: no integration test target detected (round is incomplete)

## Layers

| layer | status | exit | reproduce |
|---|---|---|---|
| unit | failed | 1 | `(cd web && npm run test -- --run) && (cd api && dotnet test tests/Acme.Portal.Tests/Acme.Portal.Tests.csproj)` |
| integration | skipped-unavailable | n/a | n/a |
| e2e | flaky | 0 | `cd e2e && npx playwright test` |
| a11y | failed | 1 | `cd e2e && npx playwright test a11y` |

## Skipped layers

- `integration` - skipped-unavailable - no integration test target detected
- A skipped layer never counts toward a pass; this round is incomplete.

## Manual items

- CHK-005 /api/* - no integration test target exists in this repository; adding one is a human decision
- a11y rule `color-contrast` at `.hero h1` - unable to determine the background color behind the text

## Coverage, baseline, suppressions

- Criteria: 5 total, 4 automated, 1 manual, 0 uncovered.
- Baseline: not used (0 pre-existing, 5 introduced).
- Suppressions: 0 valid, 0 invalid, 0 expired. An invalid or expired suppression never silences a check.

## Notes

- Automated accessibility scanning catches roughly a third to a half of real issues. A clean a11y layer is evidence, not proof of conformance.
- The only permitted response to a failure is an issue file. Deleting or skipping a test, disabling a rule, widening a tolerance, or broadening an exclusion is forbidden.
```

Severity derivations, all mechanical:

| Finding | Rule | Severity |
|---|---|---|
| `issue_001` | axe impact `critical` | `critical` |
| `issue_002` | axe impact `serious` | `high` |
| `issue_003` | inferred functional failure, no stated criterion | `medium` (default) |
| `issue_004` | axe impact `moderate` | `medium` |
| `issue_005` | flaky test | `medium` (minimum) |

Issue numbers follow that ordering, not the order the layers ran: findings are sorted by
severity, then by layer (`unit` before `integration` before `e2e` before `a11y` before
`flake`), then by file and line. That is why the two accessibility violations take
`issue_001` and `issue_002` even though the unit layer failed first, and why the flaky spec
lands last among the three `medium` findings.

Note `issue_003`: because the plan is inference-based, the failing unit test is **not** a
stated acceptance criterion, so it does not force `high`. It sits at the `medium` default.
On a repository with a requirement document, the same failure would be `high`.

Note also the `file` values on the accessibility issues. A page-level axe finding is
anchored to the **route** it was observed on, with `line: 0` — axe reports a selector and a
URL, not a source line. The selector (`#billing-email`, `.promo-banner p`) lives in the
issue body's "Observed vs expected" table.

The axe `incomplete[]` result is reported as a manual open item, never as pass and never as
fail — `a11y.failOnIncomplete` defaults to `false`. Setting it `true` would turn it into an
ordinary blocking finding instead.

```bash
python3 .agents/skills/qa-agent/scripts/qa.py verdict --round 1 --repo "$AUDIT" --qa-dir "$AUDIT_QA"
```

```json
{
  "schemaVersion": 1,
  "round": 1,
  "runId": "20260725-161104",
  "verdict": "fail",
  "rawVerdict": "fail",
  "verdictAdjusted": false,
  "complete": false,
  "reasons": [
    "layer=unit exited 1 with 1 failure(s)",
    "layer=a11y exited 1 with 3 failure(s)",
    "layer=integration skipped-unavailable: no integration test target detected (round is incomplete)",
    "verdict read from the sealed summary.json of round 001"
  ],
  "skippedLayers": [
    {"layer": "integration", "reason": "no integration test target detected"}
  ]
}
```

```
[qa] verdict round=001 verdict="FAIL — INCOMPLETE (integration: skipped-unavailable)"
```

Exit code `1`.

---

## 6. What the audit deliberately did not do

- **No tests were generated.** Every plan row is `existing` or `manual`. Audit mode reports
  what the repository's own checks prove; writing new tests into someone else's repository
  is a decision the owner makes.
- **No files were written inside the repository.** Everything lives under
  `/tmp/audit-acme/qa`, because of `--qa-dir`.
- **Nothing was staged or committed.** `generation.autoStage` is `false` and no commit is
  ever created.
- **No failing check was weakened.** The flaky e2e spec was not quarantined, the failing
  rounding test was not skipped, and no axe rule was disabled — the three most tempting
  moves on an unfamiliar repository, and all three forbidden.
- **No baseline was created silently.** Creating one would have reclassified all five
  findings as informational and produced a green audit of a repository with real problems.

## 7. What to hand back to the owner

Three concrete next steps, in order:

1. **Fix `issue_001` and `issue_002` first** — a critical and a high, both accessibility,
   both single-line changes.
2. **Adopt a baseline only if the team is adopting the agent**, so future rounds gate on
   newly introduced violations rather than on the accumulated set:

   ```bash
   python3 .agents/skills/qa-agent/scripts/qa.py baseline create --repo "$AUDIT" \
     --qa-dir "$AUDIT_QA" --from-run 001/20260725-161104 \
     --reason "initial adoption after external audit"
   ```

   ```
   [qa] baseline created with 5 fingerprint(s) at ../../../../tmp/audit-acme/qa/baseline.json
   ```

   This is an adoption decision, not an audit action. It belongs to the repository's
   maintainers, and it moves the five findings to `status: informational`, `severity: low`,
   non-blocking — which is correct for debt and wrong for an audit report.
3. **Add an integration target** if `/api/*` contracts matter. In .NET that means a test
   project referencing `Microsoft.AspNetCore.Mvc.Testing` and driving the API through
   `WebApplicationFactory<Program>`. The agent will detect it on the next run.

---

## 8. When axe tooling is installed but nothing can host the scan

`@axe-core/playwright` in `devDependencies` is not on its own enough. The a11y layer runs
as a filtered pass of an existing unit or e2e runner, so if the repository declares an axe
package but has no Vitest/Jest and no Playwright/Cypress target to attach it to, detection
says so precisely rather than inventing a runner:

```
[qa] layer a11y: unavailable — axe packages found (@axe-core/playwright) but no unit or e2e target can host an a11y scan
```

and `exec` skips the layer with that same reason:

```
[qa] layer=a11y status=skipped-unavailable reason="axe packages found (@axe-core/playwright) but no unit or e2e target can host an a11y scan"
```

The agent then reports, in its own words:

```
The a11y layer was skipped. @axe-core/playwright is declared, but there is no Playwright or
Cypress target for it to attach to, and an audit does not add one to a repository it does
not own.

Two ways forward:
  1. Add an end-to-end target — a playwright.config.ts and at least one spec whose file
     name contains "a11y" — and the layer becomes available with no further configuration.
  2. Keep the audit read-only and accept an incomplete round: the verdict will read
     FAIL — INCOMPLETE (a11y: skipped-unavailable), or
     PASS — INCOMPLETE (a11y: skipped-unavailable), never a bare PASS.
```

The same shape covers the commoner case where the scan file simply is not named for the
filter: the target exists, the layer is `available`, and the runner reports that no test
matched. That is a failing layer, not a silent pass.

---

## 9. When there is no test stack at all

The stopping case. A repository with source code, no test runner, no test directory, and
no test script:

```bash
python3 .agents/skills/qa-agent/scripts/qa.py detect --repo ~/audits/greenfield-app
```

```json
{
  "schemaVersion": 1,
  "repo": "/Users/gustavo.araujo/audits/greenfield-app",
  "detected": false,
  "projects": [
    {"id": "web", "root": "web", "language": "typescript", "packageManager": "npm",
     "markers": ["web/package.json"]}
  ],
  "layers": {
    "unit": {"available": false, "targets": [],
      "reason": "no unit test target detected"},
    "integration": {"available": false, "targets": [],
      "reason": "no integration test target detected"},
    "e2e": {"available": false, "targets": [],
      "reason": "no e2e test target detected (no playwright or cypress config found)"},
    "a11y": {"available": false, "targets": [],
      "reason": "axe tooling not installed (jest-axe, @axe-core/playwright)"}
  },
  "conventions": {"testFileSuffixes": [], "fileNaming": "kebab-case",
    "assertionLibraries": [], "e2eFramework": null, "componentTestLibrary": null},
  "runtimes": {
    "node": {"available": true, "version": "24.x", "detail": "v24.11.0"},
    "dotnet": {"available": false, "version": null, "detail": "dotnet not on PATH"},
    "headlessBrowser": {"available": false, "detail": "no browser-based layer detected"}
  },
  "notes": []
}
```

stderr — the four layer lines plus one closing line:

```
[qa] layer unit: unavailable — no unit test target detected
[qa] layer integration: unavailable — no integration test target detected
[qa] layer e2e: unavailable — no e2e test target detected (no playwright or cypress config found)
[qa] layer a11y: unavailable — axe tooling not installed (jest-axe, @axe-core/playwright)
[qa] no test stack detected; adding a test framework is a human decision
```

Exit code `3` (`NO_STACK`). The agent stops and says exactly this:

```
No test stack detected in /Users/gustavo.araujo/audits/greenfield-app, so this repository
cannot be verified and no verdict is available. This is a stop, not a failure.

What was looked for, and not found:
  unit         a test script in package.json, or vitest/jest in devDependencies
  integration  a .NET test project referencing Microsoft.AspNetCore.Mvc.Testing, a JS
               integration test directory, or a test:integration script
  e2e          playwright.config.* or cypress.config.*
  a11y         jest-axe, vitest-axe, or @axe-core/playwright

Choosing and installing a test framework is a human decision, not the agent's. It changes
the project's dependencies, its CI, and the conventions every future contributor follows,
and there is no defensible default. Nothing was installed and nothing was written.

Once a runner is in place — for a React + Vite frontend that is typically vitest with
@testing-library/react, and playwright for end-to-end — re-run:

  python3 .agents/skills/qa-agent/scripts/qa.py detect --repo ~/audits/greenfield-app

No round was allocated and no findings were produced. An empty round would imply the
repository was checked and found clean, which is the opposite of what happened.
```

That last paragraph is the point. The agent's failure mode must never be a green screen.
