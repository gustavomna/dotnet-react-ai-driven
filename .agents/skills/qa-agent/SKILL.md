---
name: qa-agent
description: Derives a test plan from a change's requirement artifacts or diff, detects the project's existing test stack, generates traceable tests, executes unit, integration, E2E, and accessibility layers, and writes one issue file per failure into an immutable findings round. Use when a change needs verification before review, in CI, or as a one-off audit of an unfamiliar repository. Do not use for code review, manual or exploratory testing, performance, load, security, or visual-regression testing.
---

# QA Agent

Verification, not assertion. This skill turns "the agent said it works" into artifacts: a plan
that maps each acceptance criterion to a layer, tests written into the repository's own test
layout, a run log with per-layer exit codes, and one issue file per failure.

All mechanics are delegated to a standard-library Python CLI so the judgement stays with the
agent and the bookkeeping stays reproducible:

```bash
python3 .agents/skills/qa-agent/scripts/qa.py <subcommand> [options]
```

Every subcommand prints JSON to stdout and human progress text to stderr. `--json` suppresses
the stderr prose (use it whenever you redirect stdout to a file).

## Reference Map

| Read this | For |
|---|---|
| [references/scope-resolution.md](references/scope-resolution.md) | The four scope sources, intersection semantics, monorepo derivation, requirement discovery |
| [references/stack-detection.md](references/stack-detection.md) | What is probed per ecosystem, what "available" means, the skipped-unavailable contract |
| [references/test-generation.md](references/test-generation.md) | Test headers, non-happy-path coverage, determinism, secrets, the fail-first protocol |
| [references/execution-protocol.md](references/execution-protocol.md) | Layer order, streaming, logs, flake retry, reproduce commands, timeouts |
| [references/findings-format.md](references/findings-format.md) | The exact issue file format, severity table, verdict rule, `summary.json` |
| [references/baseline-and-suppression.md](references/baseline-and-suppression.md) | Baseline gating, fingerprints, the three mandatory parts of a suppression |
| [references/configuration.md](references/configuration.md) | Full `qa.config.json` shape, every default, the decisions in force |
| [references/ci-integration.md](references/ci-integration.md) | Headless flow, gating, artifacts, pull-request reporting |
| [../a11y-testing/SKILL.md](../a11y-testing/SKILL.md) | The whole accessibility layer — component scans, page scans, keyboard and focus |

Checklists: [checklists/plan-review.md](checklists/plan-review.md),
[checklists/generated-test.md](checklists/generated-test.md),
[checklists/pre-verdict.md](checklists/pre-verdict.md),
[checklists/suppression-request.md](checklists/suppression-request.md).
Templates live in [templates/](templates/); worked runs live in [examples/](examples/).

## Never Weaken A Check

**The only permitted response to a failure is an issue file.**

In response to a failing check, all of the following are forbidden — no exceptions, no
"temporarily", no "just to get the build green":

- deleting a test
- skipping a test (`.skip`, `.only` elsewhere, `[Fact(Skip=...)]`, commenting it out)
- disabling a rule (`disableRules`, `rules: { x: { enabled: false } }`, an eslint-disable added to silence a QA finding)
- widening a tolerance
- loosening an assertion (swapping `toEqual` for `toBeTruthy`, dropping a field, matching a substring instead of the value)
- broadening an exclusion (`exclude()` on `html`, `body`, `#root`, `*`, or a whole directory)

When a human asks for one of these, refuse in these words:

> I can't do that. This skill forbids making a check pass by weakening it — deleting or
> skipping a test, disabling a rule, widening a tolerance, loosening an assertion, or
> broadening an exclusion. A check weakened in response to a failure reports safety that does
> not exist, so the failure stays recorded as `qa/rounds/001/issue_001.md` until the code is
> fixed. If this is genuinely third-party or pre-existing debt, the two supported routes are a
> recorded suppression (target + reason + expiry condition) or an explicit
> `baseline regenerate --reason "..."`. Both are reviewable, both expire, neither is silent.

Then point at [references/baseline-and-suppression.md](references/baseline-and-suppression.md)
and stop. Do not implement the weakening while explaining why it is wrong.

## Write Scope

Read access: the whole repository.

Write access, and nothing else, ever:

1. Test files — inside the repository's detected test directories, or as a new sibling test file next to an existing one.
2. `qa/` — config, baseline, suppressions, rounds, runs, logs.
3. The current findings round — `qa/rounds/NNN/` while it is unsealed.

Never write to source files, build config, CI config, `package.json`, `*.csproj`, lockfiles,
`CLAUDE.md`, or any documentation. Never stage or commit; `generation.autoStage` defaults to
`false` and generated tests are left in the working tree for the developer. Never merge, push,
tag, or release. A round is sealed the moment `summary.json` exists and is then immutable —
re-running QA allocates the next round.

## Invocation Contexts

The procedure below is the same in all three; only the marked differences apply.

| Context | Differences |
|---|---|
| **Interactive** — inside a coding agent, after a change | Full procedure. Step 3 first-run disclosure is shown to the developer. Ask for confirmation only where the plan is genuinely ambiguous (an untestable criterion, a collision with a human-authored test, a route the agent cannot reach). |
| **Headless / CI** — a pipeline step on a pull-request branch | Never prompt; where interactive mode would ask, record an open item and continue. Pass `--json` everywhere. Gate on `summary.json`. See [references/ci-integration.md](references/ci-integration.md). |
| **One-off audit** — an unfamiliar repository, no prior setup | **Read-only.** Run Steps 0, 1, 2, 3, 6, 7, 8 with existing tests only. Do **not** generate tests (Step 4), do not run fail-first verification (Step 5), do not write a baseline or suppressions unless explicitly asked. Report the coverage gaps you found instead of filling them. |

## Procedures

**Step 0: Preflight — Stack Detection (Mandatory)**
1. Run the detector:
   ```bash
   python3 .agents/skills/qa-agent/scripts/qa.py detect --repo .
   ```
2. Read `layers`, `conventions`, and `runtimes` from the output. These, not your assumptions,
   decide which runner, assertion library, file suffix, and directory each generated test uses.
3. If `detected` is `false` (exit code 3, `NO_STACK`), **stop and report**. State what was
   probed and what was absent, and recommend — do not perform — the framework choice.
   **Adding a test framework to a project is a human decision, never the agent's.** Do not run
   `npm install`, `dotnet add package`, or any other dependency mutation. This is the end of
   the round.
4. Record each unavailable layer with its `reason`. An unavailable layer becomes
   `skipped-unavailable` later — it is not an error and it is not a pass.
5. Detail: [references/stack-detection.md](references/stack-detection.md).

**Step 1: Scope Resolution (Mandatory)**
1. Allocate the round and note its id:
   ```bash
   python3 .agents/skills/qa-agent/scripts/qa.py round new
   ```
2. Persist the detected stack into the round:
   ```bash
   python3 .agents/skills/qa-agent/scripts/qa.py detect --repo . --json > qa/rounds/001/stack.json
   ```
3. Resolve the scope with whatever sources the invocation supplied — `--path`, `--ref-range`,
   `--requirements`, `--package`, `--diff`/`--base`. When several are given the intersection
   wins; when none is given the scope defaults to the diff against the default branch:
   ```bash
   python3 .agents/skills/qa-agent/scripts/qa.py scope --diff --json > qa/rounds/001/scope.json
   ```
4. Do not hand-roll the mechanics — the script owns ref resolution, file classification,
   per-package derivation, and requirement-document discovery.
5. Read the result. **Any file with `touchesUi: true` makes the a11y layer required for this
   round, whether or not the developer asked for accessibility testing.**
6. On exit code 4 (`EMPTY_SCOPE`), stop and report what was intersected away; do not silently
   widen the scope.
7. Detail: [references/scope-resolution.md](references/scope-resolution.md).

**Step 2: Requirement Reading and Test-Plan Derivation (Mandatory)**
1. Generate the plan skeleton:
   ```bash
   python3 .agents/skills/qa-agent/scripts/qa.py plan --round 1 --scope qa/rounds/001/scope.json --stack qa/rounds/001/stack.json
   ```
2. Read every artifact in `requirementDocs` — PRDs, tech specs, task files, user-story
   catalogs, ADRs — and treat them as the source of expected behavior. Extract each acceptance
   criterion with a stable reference (`FR-3`, `US-014`, `AC-2`).
3. For **each** criterion, complete a `checks[]` row: the requirement reference, the chosen
   layer (`unit`, `integration`, `e2e`, `a11y`), the target file or route, the test file, and
   **the reason that layer was chosen**. A layer without a stated reason is an incomplete plan.
   Prefer the cheapest layer that can actually observe the criterion: pure logic to `unit`,
   contract and persistence behavior across a boundary to `integration`, a user-visible flow to
   `e2e`, anything rendering UI to `a11y`.
4. A criterion that cannot be automated is marked `status: manual` with a stated
   `manualReason`. It surfaces in `manualItems[]` as an open item — **never as a silent pass**,
   never omitted, never counted as automated coverage.
5. When no requirement artifact exists, derive expected behavior from the diff and the public
   interfaces it changes, set `inferenceBased: true`, and **state in the first line of
   `plan.md` that the plan is inference-based**. Say the same thing in the final report.
6. Verify the finished plan against [checklists/plan-review.md](checklists/plan-review.md).
7. Detail: [references/scope-resolution.md](references/scope-resolution.md).

**Step 3: First-Run Disclosure (Mandatory)**
1. On a repository this agent has not seen — no `qa/` directory yet — explain **before writing
   anything**:
   - what stack was detected, per project and per layer, including every layer reported
     unavailable and why;
   - which requirement artifacts were found, or that the plan is inference-based;
   - the exact list of files that will be created — test files by path, plus `qa/rounds/001/`;
   - that generated tests are left unstaged in the working tree.
2. In interactive mode, present this and continue unless the developer objects. In CI, print it
   into the log. In audit mode, print it and then generate nothing.
3. Never create the first `qa/` artifact before this disclosure has been emitted.

**Step 4: Test Generation (Mandatory — skipped in audit mode)**
1. Write tests into the directories and with the suffixes reported in `conventions`, following
   the discovered assertion library and fixture style. Do not introduce a second convention.
2. Every generated test carries a header naming the requirement and criterion it covers.
3. Interactive components get their non-happy states — error, loading, disabled, empty — not
   only the success path.
4. **Never overwrite a human-authored test.** Extend it, or add a sibling file, and report the
   collision in the round.
5. Tests must be deterministic: no wall-clock dependence, no unseeded randomness, no calls to
   live third-party services. Secrets come from the environment and are **never** written into
   tests, findings, or logs.
6. For the a11y layer, follow [../a11y-testing/SKILL.md](../a11y-testing/SKILL.md) — it owns
   component scanning, page scanning, the fixed WCAG 2.2 AA tag set, and the keyboard and
   focus-order checks that axe does not cover.
7. Check each generated file against
   [checklists/generated-test.md](checklists/generated-test.md).
8. Detail: [references/test-generation.md](references/test-generation.md).

**Step 5: Fail-First Verification (Mandatory — skipped in audit mode)**
1. Per ADR-006, **a test counts as coverage only once it has been proven to fail for the right
   reason.** A test that passes unconditionally is worse than no test: it reports safety that
   does not exist.
2. For each new test, either run it against the pre-change state (stash or check out the base
   revision) and observe the failure, or invert one assertion, observe the failure, and restore
   it. Record which method was used.
3. Confirm the failure message matches the criterion under test. A test that fails because of a
   missing import, a bad selector, or an unresolved fixture has proven nothing — fix it and
   repeat.
4. A test that cannot be made to fail is not coverage. Remove it from the plan's coverage
   count, or replace it, and say so.
5. Detail: [references/test-generation.md](references/test-generation.md).

**Step 6: Execution (Mandatory)**
1. Run every available layer in one command:
   ```bash
   python3 .agents/skills/qa-agent/scripts/qa.py exec --round 1 --stack qa/rounds/001/stack.json --scope qa/rounds/001/scope.json --plan qa/rounds/001/plan.json
   ```
2. Layers run in the order `unit → integration → e2e → a11y`. **A failing layer never stops the
   remaining layers** — one round reports every problem.
3. Watch the streamed progress on stderr; a long suite must never be mistaken for a hang:
   ```
   [qa] layer=unit status=running command="npm run test -- --run" cwd=frontend
   [qa] layer=unit status=failed exit=1 duration=12.4s failures=3
   ```
4. Do not re-run a layer by hand to "check" a failure, and do not edit a runner's config to
   make it quieter. Failures belong in Step 7.
5. Detail: [references/execution-protocol.md](references/execution-protocol.md).

**Step 7: Findings Reporting (Mandatory)**
1. Emit the findings:
   ```bash
   python3 .agents/skills/qa-agent/scripts/qa.py report --round 1 --plan qa/rounds/001/plan.json
   ```
2. One `issue_NNN.md` per failure — never combine unrelated problems into one file. Numbering
   is zero-padded to three digits and continues from the highest existing issue in the round.
3. Complete each issue by hand where the script cannot: the observed-versus-expected table, the
   requirement reference, and a **concrete** suggested fix naming the file and line and the
   reason the code behaves as it does. "Investigate the failure" is not a suggested fix.
4. A clean round writes no issue files and records the pass verdict in `summary.md` and
   `summary.json`.
5. Baseline-matched findings are forced to `severity: low`, `status: informational`, and never
   block. Introduced findings gate normally.
6. Detail: [references/findings-format.md](references/findings-format.md) and
   [references/baseline-and-suppression.md](references/baseline-and-suppression.md).

**Step 8: Verdict and Handoff (Mandatory)**
1. Work through [checklists/pre-verdict.md](checklists/pre-verdict.md), then confirm:
   ```bash
   python3 .agents/skills/qa-agent/scripts/qa.py verdict --round 1
   ```
2. A round is `pass` only when every **executed** layer exited zero and no test is marked
   flaky. A test that passes on retry is `flaky`, never `passed`.
3. A skipped layer never counts toward a pass. When any layer was skipped, `complete` is
   `false` and the verdict line reads `PASS — INCOMPLETE (a11y: skipped-unavailable)`, never a
   bare `PASS`. Set `gate.skippedLayers` to `"fail"` to promote a skip to a failure.
4. Report, in this order: the verdict word (`PASS` / `PASS — INCOMPLETE` / `FAIL`), per-severity
   counts, the first few issues, the path to the rest, the run directory, and any manual open
   items. Never dump raw runner output. `PASS` and `FAIL` are written words — never colour
   alone, and the summary must still read correctly line by line in a screen reader.
5. Hand off and stop. The round is now sealed. **Do not merge, push, tag, release, or fix the
   findings** — acting on a verdict is a human decision. Fixes re-enter on the next round.

## Honest Limits

State these in the report; do not let a green verdict imply more than it proves.

- Automated scanning proves what it proves. A passing round means the executed checks passed —
  not that the feature is correct, and not that untested behavior works.
- Coverage is asserted **against the stated criteria in the plan**, not against a
  line-percentage threshold. `coverage.uncovered` counts criteria with no check, not lines.
- Automated accessibility scanning catches roughly **a third to a half** of real accessibility
  issues. Report what was proven; **never claim WCAG compliance or conformance.**
- An inference-based plan is a guess at intent. Say so every time.
- A skipped layer proves nothing about that layer.

## Not This Skill's Job

- **Code review.** Review reads intent and design; QA executes checks. Use `run-review`.
- **Manual and exploratory testing.** What cannot be automated is marked `manual` and surfaces
  as an open item. This skill does not simulate a human tester.
- **Performance, load, and security testing.** Separate disciplines, separate tooling.
- **Visual regression testing.** Requires baseline image infrastructure this version does not take on.
- **Choosing or installing a test framework.** It reports and stops.
- **Merging, pushing, or releasing.** It reports a verdict and nothing more.

## Error Handling

- **No stack detectable** (exit 3): stop and report. Name what was probed and what was missing,
  recommend a framework without installing it, and end the round. Never scaffold a runner.
- **Empty scope** (exit 4): report which sources were intersected and which file set each
  produced. Ask for an explicit `--path` or `--ref-range` rather than widening the scope
  yourself. A docs-only change legitimately has nothing to run — say that plainly.
- **Missing headless browser**: the `e2e` and page-level `a11y` layers report
  `skipped-unavailable` with the reason. Never mark them passed, never substitute a
  component-only scan and call the page covered. Report the install command as a recommendation
  and let a human run it. Component-level a11y may still run if its tooling is present.
- **A layer times out**: status `failed`, `timedOut: true`, exit code 124. Report it as a
  failure with the reproduce command; do not raise `execution.timeoutSeconds` to make it pass.
  Raising a timeout is a deliberate configuration change, not a response to a failure.
- **A sealed round** (exit 6): never edit or delete a sealed round. Allocate the next one with
  `round new` and reference the prior round in the new summary.
- **Invalid suppressions** (exit 5): the check **runs anyway** and the invalid entry is reported
  in `summary.json` under `suppressions.invalid`. Do not repair a suppression to make a finding
  disappear; report what is missing (target, reason, or expiry) and let a human decide.
  Expired suppressions do not suppress.
- **Human-authored test collision**: never overwrite. Extend the existing file, or add a sibling
  file whose name makes the relationship obvious, and report the collision in the round summary
  so a human can reconcile the two.
- **Runner produces no machine-readable report**: parse the log conservatively, and when the
  failure list cannot be determined, emit one issue for the layer citing the log path and the
  exact reproduce command rather than inventing per-test findings.
