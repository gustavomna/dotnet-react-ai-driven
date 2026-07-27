# CI Integration

The headless context. A pipeline step runs the agent against a pull-request branch, fails the
job on a `fail` verdict, publishes the round as artifacts, and posts the per-severity counts
back to the pull request.

Nothing about the procedure changes — the same steps, the same layers, the same issue files.
What changes: the agent never prompts, `--json` is used everywhere, and the gate is machine-read.

## The headless flow

```bash
# 0. Preflight. Exit 3 means no stack — report and stop, never install one.
python3 .agents/skills/qa-agent/scripts/qa.py detect --repo . --json > /tmp/stack.json

# 1. Allocate the round and resolve scope against the pull request's base.
python3 .agents/skills/qa-agent/scripts/qa.py round new --json > /tmp/round.json
python3 .agents/skills/qa-agent/scripts/qa.py detect --repo . --json > qa/rounds/001/stack.json
python3 .agents/skills/qa-agent/scripts/qa.py scope --diff --base "$GITHUB_BASE_REF" --json > qa/rounds/001/scope.json

# 2. Plan.
python3 .agents/skills/qa-agent/scripts/qa.py plan --round 1 \
  --scope qa/rounds/001/scope.json --stack qa/rounds/001/stack.json --json

# 3. Suppression hygiene, before anything runs. Exit 5 = malformed entries.
python3 .agents/skills/qa-agent/scripts/qa.py suppress validate --json

# 4. Execute every available layer. Exit 1 here is expected on a failing round.
python3 .agents/skills/qa-agent/scripts/qa.py exec --round 1 \
  --stack qa/rounds/001/stack.json --scope qa/rounds/001/scope.json \
  --plan qa/rounds/001/plan.json --json || true

# 5. Report, then gate.
python3 .agents/skills/qa-agent/scripts/qa.py report --round 1 --plan qa/rounds/001/plan.json --json
python3 .agents/skills/qa-agent/scripts/qa.py verdict --round 1 --json
```

`run-qa-agent.sh` at the repository root wraps this sequence for a harness-driven run; a
ready-to-copy workflow lives at [../examples/ci/github-actions.yml](../examples/ci/github-actions.yml).

Notes for a CI checkout:

- Fetch enough history for the base ref to resolve (`fetch-depth: 0`, or an explicit
  `git fetch origin "$GITHUB_BASE_REF"`). A shallow clone degrades scope resolution to the
  working-tree diff, which silently narrows the round.
- Install browsers explicitly in the workflow (`npx playwright install --with-deps chromium`)
  **as a pipeline step**. The agent itself never installs anything; when the browsers are
  absent the `e2e` and page-level `a11y` layers report `skipped-unavailable`.
- Never pass `--no-baseline` or `--no-retry-failed` to make a pipeline greener.

## Gating on `summary.json`

Gate on the machine artifact. Never parse `summary.md`, never grep the runner logs, never read
prose. Two fields decide the job:

| Field | Gate |
|---|---|
| `verdict` | `"fail"` fails the job |
| `complete` | `false` fails the job when `gate.skippedLayers` is `"fail"` |

`exec` and `verdict` already exit 1 on a failing verdict, so the simplest gate is the exit
code. When the job needs the counts as well, read the JSON with the stdlib:

```bash
python3 - <<'PY'
import json, sys
s = json.load(open("qa/rounds/001/summary.json"))
c = s["counts"]
print(f"verdict={s['verdict']} complete={s['complete']} "
      f"critical={c['critical']} high={c['high']} medium={c['medium']} low={c['low']}")
if s["verdict"] != "pass" or not s["complete"]:
    sys.exit(1)
PY
```

`verdict` and `complete` are separate on purpose. A round where every executed layer passed but
the a11y layer was skipped is **not** a clean run, and the job log must say
`PASS — INCOMPLETE (a11y: skipped-unavailable)`, never a bare `PASS`.

## Recommended: `gate.skippedLayers: "fail"` in CI

The default is `"warn"` because a developer running interactively on a laptop without browsers
installed still wants the unit and integration signal.

**CI should set `"fail"`.** In a pipeline, a skipped layer is an infrastructure defect, not an
acceptable local limitation: a missing browser, missing axe packages, or a mis-set config would
otherwise quietly shrink the gate until the job proves nothing while still printing green.

```json
{"gate": {"skippedLayers": "fail", "staleRound": "warn", "flaky": "fail"}}
```

Keep `gate.flaky` at `"fail"`. A test that passes on retry is `flaky`, never `passed`, and a
pipeline that tolerates flakes trains everyone to re-run the job instead of reading it.

## Publishing findings as artifacts

Upload the whole round directory. Findings and run artifacts are plain markdown and JSON,
readable without the tool that wrote them — that is the point of ADR-002.

Upload `qa/rounds/001/` with:

- `summary.md`, `summary.json` — the verdict and the machine gate
- `plan.md`, `plan.json` — what was checked and why, including manual open items
- `issue_*.md` — one per failure, each self-contained with a reproduce command
- `runs/<runId>/*.log`, `run.json` — raw per-layer output and exit codes

Upload the artifact **even when the job fails** (`if: always()`); the failing run is exactly the
one whose evidence is needed. Retain it at least as long as the pull request stays open.

Logs, `run.json`, and issue files are already redacted — anything matching a
token/secret/password/key/credential pattern is `***REDACTED***`. Do not add a step that echoes
raw runner output into the job log or a pull-request comment, which would bypass that.

## Posting counts back to the pull request

Post the counts, not the wall of output. A comment leads with the verdict word and the
per-severity counts, then the first few issues, then a link to the artifact.

```
FAIL — QA round 001 (6 findings)

| critical | high | medium | low |
|---|---|---|---|
| 0 | 2 | 1 | 3 |

- issue_001 (high) frontend/src/components/foo.tsx:42 — Empty state renders the loading spinner
- issue_002 (high) frontend/src/components/foo.tsx:57 — Retry button is not keyboard reachable
- issue_003 (medium) e2e/app.spec.ts:18 — "creates an item" flaky (passed on retry)

3 more findings, 2 manual open items, and the full run log in the qa-round-001 artifact.
Layers: unit FAIL, integration PASS, e2e FLAKY, a11y skipped-unavailable (axe tooling not installed).
```

Requirements for the comment:

- `PASS`, `PASS — INCOMPLETE`, and `FAIL` are written words. Never colour or an emoji alone, and
  it must read correctly line by line in a screen reader.
- Every layer's status appears, including skipped ones with their reason.
- Manual open items are stated. They are open items, **never silent passes**.
- Say what the round proves and no more: automated accessibility scanning catches roughly a
  third to a half of real issues, and coverage is asserted against stated criteria, not a line
  percentage. Never let a comment imply compliance.
- Update one comment in place across pushes rather than appending a new one each time.

## What CI must not do

- Not merge, push, tag, or release on a passing round. The agent reports a verdict; acting on it
  is a human decision.
- Not commit generated tests. `generation.autoStage` is `false`; tests belong to the developer's
  commit.
- Not edit or delete an earlier round. Rounds are immutable; a re-run allocates the next one.
- Not auto-fix findings, auto-regenerate the baseline, or auto-grant a suppression to clear a
  red build. The only permitted response to a failure is an issue file.
