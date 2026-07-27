# Checklist — Pre-Verdict

Walk this list **after execution and before publishing a verdict**. It is the last gate
between a run and a claim. Every item is phrased so that **yes = proceed**. A single `no`
means the verdict is not yet publishable.

One item is an **instant stop**: it is marked as such and cannot be resolved by continuing.

Inputs: `qa/rounds/NNN/runs/<runId>/run.json`, the per-layer logs, and the issue files
written by `report`.

---

## 1. Every layer accounted for

- [ ] **Does `run.json` contain one entry per layer in `unit`, `integration`, `e2e`, `a11y` order, with no layer missing?**
      *If no:* re-run. A layer absent from `run.json` is neither a pass nor a skip; it is an unknown, and unknowns must never reach a verdict.
- [ ] **Did every layer either actually execute, or carry `status: "skipped-unavailable"` with a non-empty `reason` naming the missing tooling or runtime?**
      *If no:* fill in the reason from the stack document. "a11y: skipped" is not a reason; "axe tooling not installed (jest-axe, @axe-core/playwright)" is.
- [ ] **Did a failing layer let the later layers run?**
      *If no:* re-run. One round reports every problem; stopping at the first failure hides the rest and costs a whole extra round.
- [ ] **Does every executed layer record its exact command, `cwd`, and a `reproduce` string a human can paste into a terminal?**
      *If no:* fix the record. An unreproducible failure is an unactionable failure.
- [ ] **Does every layer have a log file on disk, with the raw runner output preserved?**
      *If no:* re-run with capture enabled.
- [ ] **Are all logs, `run.json`, and issue files free of secrets — no token, password, key, or credential value in plain text?**
      *If no:* stop, redact, and re-check. Committed artifacts are forever.
- [ ] **Are timed-out layers recorded as `status: "failed"` with `timedOut: true` and exit code 124, rather than as a skip?**
      *If no:* correct them. A timeout is a failure with a cause, not an absence.

## 2. One issue per failure

- [ ] **Does every failure in `run.json` have exactly one corresponding `issue_NNN.md`?**
      *If no:* emit the missing files. A failure without an issue file did not happen, as far as any downstream consumer can tell.
- [ ] **Does every `issue_NNN.md` correspond to exactly one failure, with no file combining two unrelated problems?**
      *If no:* split it. One issue per failure is the output contract; batching defeats mechanical remediation.
- [ ] **Does issue numbering continue from the highest existing `issue_*.md` in this round, zero-padded to three digits, with no reuse and no gaps?**
      *If no:* renumber before anything reads them.
- [ ] **Does every issue carry frontmatter with exactly `status`, `file`, `line`, `severity`, `author`, `source` — in that order, no extras, no omissions?**
      *If no:* correct it. Consumers parse this frontmatter positionally-agnostic but schema-strict; an extra key breaks them.
- [ ] **Is every frontmatter value that contains `:`, `#`, `{`, `[`, or a leading `-`/`?`, or is empty, double-quoted so the YAML still parses?**
      *If no:* quote it. An unparseable issue file is invisible to CI.
- [ ] **Does every issue body carry all five sections — failing assertion, observed vs expected, reproduce, requirement, suggested fix?**
      *If no:* complete them. "Suggested fix" may say the cause is undetermined, but the section is never omitted.
- [ ] **Is every `reproduce` command copy-pasteable and scoped to the single failing test, not the whole suite?**
      *If no:* narrow it. `npm run test -- --run <file> -t "<name>"` and `dotnet test --filter "FullyQualifiedName~<name>"` are the shapes.
- [ ] **Is every severity consistent with the severity table — stated-criterion failure at minimum `high`, axe `critical`/`serious`/`moderate`/`minor` mapping to `critical`/`high`/`medium`/`low`, flake at minimum `medium`, baseline match forced to `low` + `informational`?**
      *If no:* recompute. Severity is derived, never negotiated.
- [ ] **On a clean round, were zero issue files written, and is the pass verdict recorded in both `summary.md` and `summary.json`?**
      *If no:* remove the stray files. A clean round is proven by the absence of issues plus the presence of the summary.

## 3. Nothing was weakened — INSTANT STOP

- [ ] **Was every failure answered with an issue file, and with nothing else?**
      *If no:* **stop immediately.** Do not publish a verdict. Revert the weakening, restore the original check, and report both the original failure and the attempted weakening.

The following, done in response to a failure, are all forbidden and all trigger the stop:

| Weakening | What it looks like |
|---|---|
| Deleting a test | The failing test no longer exists in the working tree |
| Skipping a test | `it.skip`, `describe.skip`, `test.fixme`, `[Fact(Skip = "...")]`, `--filter` narrowed to dodge it |
| Disabling a rule | `disableRules`, `rules: { x: { enabled: false } }`, an eslint-disable added over the failing line |
| Broadening an exclusion | `exclude("body")`, `exclude("#root")`, a new glob excluding the failing file |
| Widening a tolerance | Timeout raised, retry count raised, numeric epsilon loosened, `toBeCloseTo` precision dropped |
| Loosening an assertion | `toBe` downgraded to `toBeTruthy`, an exact string relaxed to a substring, an assertion deleted from an otherwise passing test |
| Re-scoping the round | Removing the failing file from scope so the check no longer applies |

- [ ] **Are all pre-existing tests byte-identical to their state before this round, apart from additions the plan recorded?**
      *If no:* revert and re-run.
- [ ] **Are all configuration files — `vitest` config, `playwright.config.ts`, `.csproj`, lint config, axe options — unchanged by this round?**
      *If no:* revert. Config changes to make a check pass are weakenings wearing a different hat.

## 4. Flakiness reported honestly

- [ ] **Is every test that failed and then passed on retry recorded in `flakes[]` with its layer marked `flaky`?**
      *If no:* correct it. A passing retry does not erase the failure that preceded it.
- [ ] **Is no flaky test reported anywhere as `passed`?**
      *If no:* fix the report. This is the single most tempting misreport in the whole workflow.
- [ ] **Does every flaky test have an issue file at severity `medium` or higher?**
      *If no:* emit it. Flakiness is a defect in the test or in the code, and it is always somebody's to fix.
- [ ] **Does the verdict read `fail` when any test is flaky, regardless of the final exit codes?**
      *If no:* recompute. A round is `pass` only when every executed layer exits zero **and** no test is marked flaky.
- [ ] **Was the retry limited to one attempt on the failed tests, rather than repeated until green?**
      *If no:* discard the run and re-run. Retrying to green is a weakening.

## 5. Baseline and suppressions

- [ ] **Does `suppress validate` exit 0, with no malformed entry?**
      *If no:* list the invalid entries in the summary and confirm each corresponding check **ran anyway**. An invalid suppression suppresses nothing.

```bash
python3 .agents/skills/qa-agent/scripts/qa.py suppress validate
```

- [ ] **Does every applied suppression carry all three parts — `target`, `reason`, `expires`?**
      *If no:* it is invalid; the check runs and the entry is reported.
- [ ] **Is every expired suppression reported as `expired` and treated as not suppressing?**
      *If no:* recompute against today's date.
- [ ] **Is no suppression a rule-scoped a11y suppression or a broad exclude?**
      *If no:* reject it outright and let the finding through. Axe rule disabling and `html`/`body`/`#root`/`*` excludes are never valid.
- [ ] **Does `summary.json` report the suppression tallies (`valid`, `invalid`, `expired`)?**
      *If no:* add them. Suppressions that nobody counts are suppressions that nobody reviews.
- [ ] **When a baseline is in use, is every baseline-matched finding forced to `severity: low`, `status: informational`, and excluded from gating?**
      *If no:* recompute the partition with `baseline compare`.
- [ ] **Are `preexisting` and `introduced` counts both present in `summary.json`, so the reader can see how much debt was carried?**
      *If no:* add them.
- [ ] **Was the baseline left unmodified by this round?**
      *If no:* revert. The baseline changes only through `baseline regenerate --reason TEXT`, never as a side effect of a run.

## 6. The verdict line itself

- [ ] **Is the verdict written as the word `PASS` or `FAIL`, never conveyed by colour, an icon, or a symbol alone?**
      *If no:* rewrite. The output must stay meaningful read linearly by a screen reader and in a monochrome log.
- [ ] **Does `verdict` equal `pass` only when every executed layer exited zero and no test is flaky?**
      *If no:* recompute.
- [ ] **When any layer was skipped, is `complete` set to `false`, is `skippedLayers[]` populated, and does the human line read `PASS — INCOMPLETE (<layer>: <reason>)` rather than a bare `PASS`?**
      *If no:* rewrite the line. A bare `PASS` on an incomplete round is the exact false assurance this agent exists to prevent.
- [ ] **When `gate.skippedLayers` is `"fail"`, was the skip promoted to a `fail`?**
      *If no:* recompute against the effective configuration.
- [ ] **Does the summary lead with per-severity counts, then the first few issues, then the path to the rest — rather than a wall of raw runner output?**
      *If no:* restructure. The raw output stays in the layer logs where it belongs.
- [ ] **Does the summary state the round directory and the run directory paths?**
      *If no:* add them. The verdict is a pointer to evidence, not a substitute for it.
- [ ] **Does the summary list every manual item as an open item, never folded into the pass?**
      *If no:* surface them.
- [ ] **When any a11y layer ran, does the summary state that automated scanning catches roughly a third to a half of real issues, and stop short of claiming compliance?**
      *If no:* add the statement. Every a11y report carries it.
- [ ] **Do `summary.md` and `summary.json` agree on verdict, completeness, and every count?**
      *If no:* regenerate both from the same run.

---

## Publish gate

```bash
python3 .agents/skills/qa-agent/scripts/qa.py verdict --round <N>
```

Exit 0 means `pass`, exit 1 means `fail`. Publish only when every box above is ticked and
this command's verdict matches the one written in `summary.md`. If they disagree, the
summary is wrong — regenerate it, never edit the verdict by hand.
