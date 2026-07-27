# Configuration

**Configuration is optional.** Every setting has a working default derived from the detected
stack, and the agent must operate on a repository it has never seen with no project-specific
configuration at all. A first run that requires a config file is a broken first run.

Configuration lives at `qa/qa.config.json` — beside the artifacts it governs, under version
control, readable without the tool that wrote it. It is not stored in `package.json`, not in a
`*.csproj`, and not in agent-definition frontmatter.

`--config PATH` overrides the location; a missing file is fine and never an error. The user's
file is deep-merged over the defaults, so a config naming one key keeps the defaults for
everything else.

## Full shape — every key optional

```json
{
  "schemaVersion": 1,
  "roundSequence": "independent",
  "outputDir": "qa",
  "layers": {"unit": true, "integration": true, "e2e": true, "a11y": true},
  "gate": {"skippedLayers": "warn", "staleRound": "warn", "flaky": "fail", "baselineOnly": false},
  "scope": {"defaultBase": "main", "packages": []},
  "generation": {"autoStage": false, "testDirOverrides": {}},
  "a11y": {"tags": ["wcag2a", "wcag2aa", "wcag22aa"], "routes": [], "failOnIncomplete": false},
  "execution": {"timeoutSeconds": 1800, "retryFailedOnce": true}
}
```

## Every default

| Key | Default | Meaning |
|---|---|---|
| `schemaVersion` | `1` | Document version. Every JSON artifact in this bundle carries it. |
| `roundSequence` | `"independent"` | QA rounds keep their own sequence. A path to an external counter file makes it shared. |
| `outputDir` | `"qa"` | Where rounds, baseline, and suppressions live. `--qa-dir` overrides per invocation. |
| `layers.unit` | `true` | Include the layer when it is available. Setting `false` skips it deliberately — it is still reported in `skippedLayers[]`. |
| `layers.integration` | `true` | As above. |
| `layers.e2e` | `true` | As above. |
| `layers.a11y` | `true` | As above. **Never set this `false` to clear accessibility findings** — that is the never-weaken rule. |
| `gate.skippedLayers` | `"warn"` | `"warn"` keeps `verdict: pass` with `complete: false`; `"fail"` promotes a skip to a failing verdict. **CI should set `"fail"`.** |
| `gate.staleRound` | `"warn"` | Whether a missing or stale QA round blocks a completion claim. `"block"` opts in. |
| `gate.flaky` | `"fail"` | A flaky test fails the round. A flaky test is never reported as passed regardless of this key. |
| `gate.baselineOnly` | `false` | **Off by default — the verdict rule is absolute.** A round is `pass` only when every executed layer exited zero and no test is flaky, so the baseline rule is expressed in severity and status (`low` + `informational`, excluded from the blocking counts), not by flipping the verdict. Setting `true` lets a round whose *every* failure is baseline-matched or covered by a valid suppression gate green; when it fires, `summary.json` records `rawVerdict` and `verdictAdjusted: true`, and `reasons[]` says so, so `run.json` and `summary.json` can never silently disagree. Never applies over a flaky or timed-out layer. |
| `scope.defaultBase` | `"main"` | Base for the default-to-diff rule. Resolution still tries `origin/HEAD` first. |
| `scope.packages` | `[]` | Empty means per-changed-package auto-derivation. A non-empty list pins the packages. |
| `generation.autoStage` | `false` | **The agent never stages or commits.** Generated tests are left in the working tree. |
| `generation.testDirOverrides` | `{}` | Per-project override of the detected test directory, for layouts detection gets wrong. |
| `a11y.tags` | `["wcag2a","wcag2aa","wcag22aa"]` | **Fixed.** Conformance target is WCAG 2.2 Level AA. Narrowing this is a weakening. |
| `a11y.routes` | `[]` | Routes for page-level scanning. Empty means derive from the router and the scope. |
| `a11y.failOnIncomplete` | `false` | axe `incomplete[]` entries are reported as manual open items, never as pass or fail, unless this is `true`. |
| `execution.timeoutSeconds` | `1800` | **Per layer**, not per round. Raising it in response to a timeout is forbidden. |
| `execution.retryFailedOnce` | `true` | Re-run only the failed tests once to identify flakiness — never to forgive it. |

## The decisions in force

The PRD left six questions open. All six are decided, and each is configurable so a team can
disagree explicitly rather than silently.

| Question | Decision | Config key |
|---|---|---|
| Share round numbering with code-review rounds? | **Independent sequence** — QA history stays readable on its own, and a QA round is not implied to correspond to a review round that does not exist. | `roundSequence` |
| Where does configuration live? | **`qa/qa.config.json`**, optional, every key defaulted from the detected stack. Beside the artifacts, under version control, no manifest pollution. | — (the file's location) |
| Does a missing or stale QA round block a completion claim? | **Warn by default**, `"block"` opt-in. A documentation-only change legitimately has nothing to run, and hard-blocking it teaches people to bypass the gate. | `gate.staleRound` |
| Monorepo scope | **Auto-derive per changed package**; `--package` narrows. A change to one package does not drag the whole repository into the round. | `scope.packages` |
| Commit generated tests? | **Never.** Written to the working tree; staging and committing stay with the developer, who owns the commit and its message. | `generation.autoStage` |
| Baseline invalidation on a dependency upgrade | Explicit `baseline regenerate --reason TEXT`, appended to `history[]`. **Never automatic** — an automatic reset is an unreviewable amnesty. | — (`baseline regenerate`) |

## What configuration may not do

Configuration tunes where things run and how strict the gate is. It cannot switch checking off.

- No key disables an axe rule. `disableRules` and `rules: {x: {enabled: false}}` are rejected
  wherever they appear.
- No key permits a broad `exclude()` — `html`, `body`, `#root`, `*` are always rejected.
- No key removes the fail-first requirement, the one-issue-per-failure rule, or round
  immutability.
- No key suppresses a finding. Suppression has its own recorded, expiring format — see
  [baseline-and-suppression.md](baseline-and-suppression.md).
- Editing `qa.config.json` in response to a failing round is the never-weaken rule under a
  different filename. Configuration changes are deliberate decisions taken in advance.

## Global invocation options

These are flags, not config, and are accepted by every subcommand:

| Flag | Default | Meaning |
|---|---|---|
| `--repo PATH` | cwd | Repository root, resolved to an absolute path |
| `--qa-dir PATH` | `<repo>/qa` | Output directory |
| `--config PATH` | `<qa-dir>/qa.config.json` | Config file; missing is fine |
| `--json` | off | Suppress the stderr prose. stdout is always JSON either way. |

## Exit codes

| Code | Name | Meaning |
|---|---|---|
| 0 | `OK` | Success / verdict pass |
| 1 | `FAIL` | Verdict fail (findings exist) |
| 2 | `USAGE` | Bad arguments |
| 3 | `NO_STACK` | No test stack detectable — stop and report |
| 4 | `EMPTY_SCOPE` | Scope resolved to nothing |
| 5 | `INVALID_SUPPRESSION` | One or more suppressions are malformed |
| 6 | `SEALED_ROUND` | Attempt to mutate a sealed round |
| 7 | `RUNTIME_ERROR` | Unexpected internal error (stack trace on stderr) |
