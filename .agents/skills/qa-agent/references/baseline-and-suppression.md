# Baseline and Suppression

Two mechanisms exist so a strict gate can be adopted on a real repository. Both are recorded,
reviewable, and expire. Neither is ever a response to a failing check the agent just produced —
see the never-weaken rule in [../SKILL.md](../SKILL.md).

## Baseline: gate on what this change introduced

A repository with accumulated debt cannot adopt a gate that blocks on every pre-existing
violation — it would block every run — and it must not adopt one that hides regressions. The
baseline splits the difference: **the round gates on violations introduced by the current
scope.**

```bash
python3 .agents/skills/qa-agent/scripts/qa.py baseline create --from-run 1/20260725-140233 --reason "initial adoption"
python3 .agents/skills/qa-agent/scripts/qa.py baseline compare --run 2/20260726-091500
python3 .agents/skills/qa-agent/scripts/qa.py baseline show
```

The gating rule:

| Finding | Treatment |
|---|---|
| Fingerprint **is** in `qa/baseline.json` | **Pre-existing.** Forced `severity: low`, `status: informational`. It appears as an issue file, it is counted, and it **never blocks.** |
| Fingerprint is **not** in the baseline | **Introduced.** Gates normally at its natural severity. |

`baseline compare` prints `{"preexisting": [fp...], "introduced": [fp...]}` and `summary.json`
carries `baseline: {"used": true, "preexisting": 3, "introduced": 2}`.

`--no-baseline` on `report` ignores the baseline entirely — useful for a full-debt audit, never
for a gating run that wants a greener number.

Pre-existing findings are still written and still visible. The baseline reduces their severity;
it does not delete them. A repository whose debt is invisible cannot pay it down.

## Fingerprints

```
sha256:<hex of f"{source}|{rule}|{normFile}|{normTarget}">
```

- `source` — `unit`, `integration`, `e2e`, `a11y`, `flake`, `plan`.
- `rule` — the axe rule id, or `None` for a test failure.
- `normFile` — repo-relative POSIX path.
- `normTarget` — the axe target selector, or the test id.

**There is deliberately no line number in the fingerprint.** A violation that moves down forty
lines because an import was added is the same violation; a fingerprint that included the line
would report it as newly introduced and block a no-op change.

The consequences, which must be understood before trusting the baseline:

- **Renaming a file or a test changes the fingerprint**, so the finding is reported as
  introduced. That is correct behavior — the agent cannot tell a rename from a new problem — and
  it is resolved by a deliberate `baseline regenerate --reason "renamed x to y"`, not by
  loosening the fingerprint.
- **Two identical violations on the same target in the same file collapse to one fingerprint.**
  Distinct nodes have distinct `target` selectors, so this is rare in practice.
- A fingerprint proves identity, not correctness. A baselined violation is still a violation.

## Regeneration requires an explicit reason

```bash
python3 .agents/skills/qa-agent/scripts/qa.py baseline regenerate --reason "playwright 2.0 upgrade changed the rule set"
```

- `--reason TEXT` is **required**. Without it: exit 2 (`USAGE`). The command cannot be run by
  accident and cannot be run without leaving a sentence someone can disagree with.
- Regeneration appends to `history[]` with `at`, `reason`, and `by`. The history is never
  truncated — it is the audit trail of every time the bar was moved.
- Regeneration is **never automatic.** A dependency upgrade that legitimately changes the
  violation set is a human decision, taken deliberately, in its own commit.
- The agent **never** regenerates the baseline in response to a failing round. "Regenerate the
  baseline so the build goes green" is the never-weaken rule with extra steps — refuse it in the
  words given in [../SKILL.md](../SKILL.md).

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-07-25T14:06:02Z",
  "generatedBy": "qa-agent",
  "reason": "initial adoption",
  "history": [{"at": "...", "reason": "playwright 2.0 upgrade changed rule set", "by": "gustavo"}],
  "fingerprints": [
    {"fp": "sha256:...", "source": "a11y", "rule": "color-contrast",
     "file": "frontend/src/legacy/widget.tsx", "target": ".legacy .btn", "severity": "medium"}
  ]
}
```

`qa/baseline.json` is **committed**. A baseline that lives only on one machine gates nothing.

## Suppression: the three mandatory parts

```bash
python3 .agents/skills/qa-agent/scripts/qa.py suppress validate
python3 .agents/skills/qa-agent/scripts/qa.py suppress list
python3 .agents/skills/qa-agent/scripts/qa.py suppress add \
  --target "a11y:aria-required-children:frontend/src/vendor/date-picker.tsx" \
  --reason "third-party date picker; upstream issue vendor/dp#412" \
  --expires 2026-12-31 \
  --scope third-party
```

A suppression is valid **only** with all three:

| Part | Requirement |
|---|---|
| `target` | The **exact** thing suppressed — `source:rule:file` or a specific test id. Not a directory, not a glob over a subtree, not a rule on its own. |
| `reason` | Why this check does not apply **here**. Non-empty, specific, and falsifiable by a reader. |
| `expires` | An ISO date (`2026-12-31`), a version (`>=2.0.0`, `v3.1`), or a ticket reference (`JIRA-123`, a URL). |

**Missing or empty any part ⇒ invalid ⇒ the check runs anyway**, and the invalid entry is
reported in `summary.json` under `suppressions.invalid`. `suppress validate` exits 5
(`INVALID_SUPPRESSION`) when any entry is malformed.

Expired suppressions (an ISO date in the past relative to `--today`, default UTC today) are
reported as `expired` and **do not suppress**. Expiry is the whole point: a suppression that
never expires is a permanently disabled check.

### Scopes

`scope` is one of:

- `third-party` — **the only scope that may exclude a subtree**, and only a genuine third-party
  widget's own DOM.
- `test` — a specific named test.
- `rule` — a specific rule on a specific file. **A `rule`-scoped suppression against an a11y rule
  is always rejected.** Disabling axe rules is forbidden outright; there is no configuration
  that permits it.

Broad excludes are **always rejected**, in every scope: a selector matching `html`, `body`,
`#root`, `*`, or an empty/whitespace selector. An exclusion that covers the page is not a
suppression, it is an off switch.

### Valid examples

```json
{"id": "sup-001",
 "target": "a11y:aria-required-children:frontend/src/vendor/date-picker.tsx",
 "reason": "third-party date picker renders its own listbox; upstream issue vendor/dp#412",
 "expires": "2026-12-31",
 "scope": "third-party",
 "addedBy": "gustavo",
 "addedAt": "2026-07-25"}
```

Valid: the target names one rule on one vendored file, the reason is specific and points at an
upstream issue a reviewer can check, and it expires on a date.

```json
{"id": "sup-002",
 "target": "e2e:e2e/app.spec.ts::uploads a file",
 "reason": "requires a signed S3 credential unavailable in the sandbox; tracked in JIRA-4471",
 "expires": "JIRA-4471",
 "scope": "test",
 "addedBy": "gustavo",
 "addedAt": "2026-07-25"}
```

Valid: one named test, an environmental reason, and a ticket that closes the loop.

### Invalid examples

```json
{"target": "a11y:color-contrast", "reason": "design is aware", "expires": ""}
```

Invalid three times over: the target names a rule with no file (it would suppress the rule
everywhere), the reason is not falsifiable, and `expires` is empty. **The check runs.**

```json
{"target": "a11y:region:#root", "reason": "layout shell", "expires": "2027-01-01", "scope": "third-party"}
```

Rejected: `#root` is a broad exclude. Rejected regardless of reason and expiry.

```json
{"target": "a11y:color-contrast:frontend/src/components/button.tsx",
 "reason": "brand palette", "expires": "2027-01-01", "scope": "rule"}
```

Rejected: a `rule`-scoped suppression against an a11y rule. A brand palette that fails contrast
is a finding for a designer, not a rule to switch off.

```json
{"target": "unit:frontend/src/", "reason": "flaky", "expires": "2026-09-01", "scope": "test"}
```

Rejected: the target is a directory, not an exact test, and "flaky" is the finding rather than a
justification for hiding it. A flaky test is at minimum `medium` severity and gets an issue file.

## Before granting one

Work through [../checklists/suppression-request.md](../checklists/suppression-request.md).
Granting a suppression is a decision about what the project will stop checking. The agent may
record one when a human asks and all three parts are present and honest; it may **never**
invent one to clear a finding it just produced.
