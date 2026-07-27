# Execution Protocol

```bash
python3 .agents/skills/qa-agent/scripts/qa.py exec --round 1 \
  --stack qa/rounds/001/stack.json \
  --scope qa/rounds/001/scope.json \
  --plan  qa/rounds/001/plan.json
```

Options: `--round N` (required), `--layer L` (repeatable, default every available layer),
`--stack FILE`, `--scope FILE`, `--plan FILE`, `--timeout S` (per layer, default 1800),
`--no-retry-failed`, `--run-id ID`. Exit 0 when the verdict is `pass`, 1 when `fail`.

Output lands in `qa/rounds/NNN/runs/<runId>/`, where `runId` is a UTC timestamp
(`20260725-140233`). A round may hold several runs; **only the latest run's `summary.json` is
authoritative.**

## Layer order, and no short-circuit

Layers execute in exactly this order:

```
unit → integration → e2e → a11y
```

Cheapest and most localized first, so the fastest signal arrives first.

**A failing layer never stops the remaining layers.** One round reports every problem the
codebase has, not the first one it hit. A developer who fixes a unit failure and then discovers
an unreported E2E failure has been made to pay for two rounds where one would have done.

The only thing that stops a layer is the layer itself finishing, or its timeout expiring.

`--layer` narrows the set (for example `--layer a11y` while iterating on an accessibility fix),
but the full set is the default and is what a verdict is normally computed from. A narrowed run
still records the layers it did not execute.

## Streamed progress

One stderr line per state change. A long suite must never be mistaken for a hang.

```
[qa] layer=unit status=running command="npm run test -- --run" cwd=frontend
[qa] layer=unit status=failed exit=1 duration=12.4s failures=3
[qa] layer=integration status=running command="dotnet test backend/tests/Backend.Api.Tests" cwd=.
[qa] layer=integration status=passed exit=0 duration=41.9s failures=0
[qa] layer=e2e status=running command="npx playwright test" cwd=.
[qa] layer=e2e status=flaky exit=0 duration=88.2s failures=0 flakes=1
[qa] layer=a11y status=skipped-unavailable reason="axe tooling not installed (jest-axe, @axe-core/playwright)"
```

The format is `key=value`, colour-independent, and meaningful when read linearly by a screen
reader. Status words are written out (`passed`, `failed`, `flaky`, `skipped-unavailable`) — never
a symbol, never a colour alone.

## Per-layer logs and exit codes

Combined stdout and stderr per layer is captured to `<run>/<layer>.log`, and the layer's entry
in `run.json` records:

| Field | Meaning |
|---|---|
| `status` | `passed` \| `failed` \| `flaky` \| `skipped-unavailable` |
| `exitCode` | The runner's exit code; `null` for a skipped layer; `124` on timeout |
| `timedOut` | `true` only when the per-layer timeout fired |
| `retried` | `true` when a flake retry ran |
| `durationMs` | Wall-clock duration |
| `command` / `cwd` | The exact argv and working directory |
| `reproduce` | A copy-pasteable single-line shell command |
| `log` | The log filename inside the run directory |
| `reason` | Why a layer was skipped; `null` otherwise |
| `failures[]` | One entry per failing test |
| `flakes[]` | One entry per test that failed then passed on retry |

**Secrets are redacted before anything is written.** Any `--flag=value` or `KEY: value` whose
name matches `TOKEN`, `SECRET`, `PASSWORD`, `KEY`, or `CREDENTIAL`, and any value matching such
an environment variable, becomes `***REDACTED***` in logs, `run.json`, and issue files. Never
work around redaction by pasting a value into an issue body.

## The exact reproduce command

Every layer, and every failure inside it, records a command a human can paste into a terminal
and get the same result. This is not optional decoration — it is what makes remediation
mechanical instead of investigative.

A reproduce command must include the working directory, the runner invocation, the target file,
and the test selector:

```bash
cd frontend && npm run test -- --run src/__tests__/foo.test.tsx -t "renders empty state"
```

```bash
dotnet test backend/tests/Backend.Api.Tests --filter "FullyQualifiedName~ItemsControllerTests.Post_ReturnsBadRequest_WhenNameEmpty"
```

```bash
npx playwright test e2e/app.spec.ts -g "creates an item"
```

Environment variables an integration or E2E layer needs are named, never valued:
`API_TOKEN=<from your environment> npx playwright test ...`.

## Flakiness: retry once, and it is still flaky

On a non-zero exit with retry enabled (`execution.retryFailedOnce`, default `true`), the layer
re-runs **only the failed tests**, once, when the runner supports targeted re-run:

| Runner | Targeted re-run |
|---|---|
| vitest | file arguments plus `-t "<name>"` |
| playwright | `--last-failed` |
| dotnet test | `--filter "FullyQualifiedName~<name>"` |

When targeted re-run is not supported, the whole layer re-runs once. `--no-retry-failed`
disables retry entirely.

**A test that passes on retry is `flaky`, never `passed.`**

- The layer's status becomes `flaky` and each such test is recorded in `flakes[]`.
- A flaky test is a finding at **minimum severity `medium`**, and it is never dismissed by the
  passing retry.
- `flaky` prevents a `pass` verdict — a round is `pass` only when every executed layer exited
  zero **and** no test is marked flaky. `gate.flaky` defaults to `"fail"`.

The reasoning: a test that passes only sometimes is not evidence about the code. It is evidence
about the test, the fixtures, or a race in the implementation — all of which need a human. The
retry exists to *identify* flakiness, not to *forgive* it.

## Timeouts

`--timeout S`, or `execution.timeoutSeconds` (default `1800`), applies **per layer**, not to the
round.

On expiry: the layer's process tree is terminated, `status` is `failed`, `timedOut` is `true`,
and `exitCode` is `124`. The partial log is kept — it is usually the fastest route to the
hanging test. Remaining layers still run.

A timeout is reported as a failure with its reproduce command. **Raising the timeout in response
to one is forbidden** — it is exactly the "widening a tolerance" move the never-weaken rule
prohibits. Changing `execution.timeoutSeconds` is a deliberate configuration decision made by a
human, in advance, for a suite that is legitimately long — never a reaction to a red run.

## Skipped layers

A layer whose detection reported `available: false` gets `status: "skipped-unavailable"`,
`exitCode: null`, and the detection reason verbatim. It is listed in `skippedLayers[]`,
`complete` becomes `false`, and the verdict line reads `PASS — INCOMPLETE (...)`. See
[stack-detection.md](stack-detection.md) and [findings-format.md](findings-format.md).
