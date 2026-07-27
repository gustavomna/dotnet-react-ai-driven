# Findings Format

The issue file is the agent's **only** output contract. Any remediation consumer — a human, a
fix agent, a CI bot — must be able to act on it without knowing anything about this skill's
internals.

```bash
python3 .agents/skills/qa-agent/scripts/qa.py report --round 1 --plan qa/rounds/001/plan.json
```

Options: `--round N` (required), `--run ID` (default: latest), `--plan FILE`, `--author NAME`
(default `qa-agent`), `--no-baseline`, `--dry-run`.

## The exact issue file

Filename `issue_NNN.md`, `NNN` zero-padded to three digits, written into `qa/rounds/NNN/`.

````markdown
---
status: open
file: frontend/src/components/foo.tsx
line: 42
severity: high
author: qa-agent
source: unit
---

# issue_003 — Empty state renders the loading spinner instead of the empty message

## Failing assertion

`expect(screen.getByText('No results')).toBeInTheDocument()` — element not found.

## Observed vs expected

| | |
|---|---|
| Expected | Empty message "No results" is rendered when `items` is `[]` |
| Observed | Loading spinner stays mounted; no empty message in the DOM |

## Reproduce

```bash
cd frontend && npm run test -- --run src/__tests__/foo.test.tsx -t "renders empty state"
```

## Requirement

`FR-3` — tasks/prd-x/prd.md — "the list shows an empty state when there are no results"

## Suggested fix

`foo.tsx:42` gates the empty branch on `items.length === 0 && !isLoading`, but `isLoading`
is never reset when the request resolves with an empty array. Reset it in the settled
branch of the effect.
````

Sections are all five, in that order, always present. An unknown requirement is written as
`inferred — derived from the exported signature of <symbol>`, not omitted. A suggested fix
names the file, the line, and the reason the code behaves as it does; "investigate the failure"
is not a suggested fix.

## Frontmatter

Keys are **exactly** `status`, `file`, `line`, `severity`, `author`, `source` — in that order,
no extras, no omissions.

| Key | Values |
|---|---|
| `status` | `open` \| `informational` (informational = baseline-matched, non-blocking) |
| `file` | Repo-relative POSIX path |
| `line` | Integer; `0` when there is no meaningful line |
| `severity` | `critical` \| `high` \| `medium` \| `low` |
| `author` | `qa-agent` unless `--author` overrides |
| `source` | `unit` \| `integration` \| `e2e` \| `a11y` \| `flake` \| `plan` |

Values containing `:`, `#`, `{`, `[`, a leading `-` or `?`, or that are empty, must be
double-quoted so the frontmatter stays valid YAML. An axe selector such as
`#root > div:nth-child(2)` in a value **must** be quoted.

`source: plan` is for planning-time findings — an unautomatable criterion, an uncovered
criterion, a collision with a human-authored test.

## One issue per failure

- **One `issue_NNN.md` per failure.** Never combine unrelated problems into one file, even when
  they share a root cause — a remediation consumer that fixes one must be able to close one.
- Three axe violations on one page are three issues. One axe rule violated by four nodes is
  four issues, one per node.
- Numbering is zero-padded to three digits and **continues from the highest existing
  `issue_*.md` in that round**. It never restarts, never reuses a number, and never renumbers
  an existing file.
- A clean round writes **no** issue files and records the pass verdict in `summary.md` and
  `summary.json`. An empty round directory with a pass summary is a correct result.

## Severity

Severity is exactly one of `critical`, `high`, `medium`, `low`.

| Situation | Severity |
|---|---|
| Failing test of an explicit **stated** acceptance criterion | at minimum **`high`** |
| a11y violation, axe impact `critical` | `critical` |
| a11y violation, axe impact `serious` | `high` |
| a11y violation, axe impact `moderate` | `medium` |
| a11y violation, axe impact `minor` | `low` |
| Flaky test | at minimum **`medium`**, never dismissed by a passing retry |
| Baseline-matched (pre-existing) finding | forced `low`, `status: informational`, non-blocking |
| Inferred (no stated criterion) functional failure | `medium` by default, escalate on judgement |

"At minimum" means the floor may be raised by judgement — data loss, an auth bypass, or a
broken primary flow justifies `critical` — never lowered. A failing stated criterion is never
`medium` because it "looks small".

## Verdict

**A round is `pass` only when every executed layer exited zero and no test is marked flaky.
Any other state is `fail`.**

```bash
python3 .agents/skills/qa-agent/scripts/qa.py verdict --round 1
```

Exit 0 on pass, 1 on fail. Prints `{"verdict":"pass|fail","complete":true,"reasons":[...]}`.

`PASS` and `FAIL` are written words. Verdicts never rely on colour, and the summary must read
correctly line by line in a screen reader.

## Skipped-layer reconciliation

Two rules are in play: a round is `pass` when every **executed** layer exits zero, and a
**skipped layer never counts toward a pass.** They reconcile like this:

1. `verdict` stays `pass` when all executed layers passed.
2. `complete` becomes `false` and `skippedLayers[]` is populated with each layer and its reason.
3. The human verdict line reads **`PASS — INCOMPLETE (a11y: skipped-unavailable)`** — never a
   bare `PASS`.
4. `gate.skippedLayers` promotes the skip to a `fail` when set to `"fail"`. Default is
   `"warn"`; CI examples set `"fail"`.

Never report a bare `PASS` on an incomplete round, and never describe a skipped layer as
"passed", "clean", or "not applicable" unless the detection reason genuinely says so.

## The reported summary

Failure output leads with counts by severity, then the first few issues, then the path to the
rest — never a wall of raw runner output.

```
FAIL — round 001 (6 findings: 0 critical, 2 high, 1 medium, 3 low)
  issue_001  high    frontend/src/components/foo.tsx:42  Empty state renders the loading spinner
  issue_002  high    frontend/src/components/foo.tsx:57  Retry button is not keyboard reachable
  issue_003  medium  e2e/app.spec.ts:18                  "creates an item" flaky (passed on retry)
  … 3 more in qa/rounds/001/
Run: qa/rounds/001/runs/20260725-140233/
Manual open items: 2 — see qa/rounds/001/summary.md
```

## `summary.json` — the machine gate

Written alongside `summary.md`. **This is what CI gates on**; nothing should parse the prose.

```json
{
  "schemaVersion": 1,
  "round": 1,
  "runId": "20260725-140233",
  "verdict": "pass|fail",
  "rawVerdict": "pass|fail",
  "verdictAdjusted": false,
  "reasons": ["every executed layer exited zero and no test was flaky"],
  "complete": true,
  "generatedAt": "2026-07-25T14:06:02Z",
  "layers": [{"layer": "unit", "status": "passed", "exitCode": 0, "reproduce": "..."}],
  "counts": {"critical": 0, "high": 2, "medium": 1, "low": 3, "total": 6},
  "issues": [{"id": "issue_001", "file": "...", "line": 24, "severity": "high",
              "source": "unit", "status": "open", "title": "..."}],
  "manualItems": [{"criterion": "FR-7 print stylesheet", "reason": "requires visual judgement"}],
  "suppressions": {"valid": 1, "invalid": 0, "expired": 0},
  "baseline": {"used": true, "preexisting": 3, "introduced": 2},
  "skippedLayers": [{"layer": "a11y", "reason": "axe tooling not installed"}],
  "coverage": {"criteria": 12, "automated": 10, "manual": 2, "uncovered": 0}
}
```

Gate on `verdict`, and on `complete` when skipped layers must block.

`rawVerdict` is the un-adjusted, layer-derived verdict — `pass` only when every executed layer
exited zero and no test was flaky. It equals `verdict` unless the opt-in `gate.baselineOnly`
fired, in which case `verdictAdjusted` is `true` and `reasons[]` says why. **A CI job that
wants the strict result gates on `rawVerdict`.** Because the adjustment is off by default,
`summary.json` and the run's `run.json` agree unless someone deliberately opted in — they are
never allowed to disagree silently.

`manualItems[]` carries
every criterion that could not be automated — they are open items, **never silent passes**.
`coverage` counts **criteria**, not lines: `automated + manual + uncovered == criteria`. There
is no line-percentage threshold anywhere in this contract.

Writing a `summary.json` **seals** the round. Sealed rounds are never edited or deleted; the
next `round new` allocates `max(existing) + 1`.
