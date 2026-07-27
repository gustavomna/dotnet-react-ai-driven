# Severity mapping — axe impact to QA Agent findings

Reference for [SKILL.md](../SKILL.md) Steps 6 and 7. This is the contract between the a11y
layer and the QA Agent's reporting layer. Deviating from it makes a11y findings incomparable
with the rest of the round.

## 1. The mapping

Severity is exactly one of `critical`, `high`, `medium`, `low`. Nothing else is a severity.

| axe impact | QA severity |
|---|---|
| `critical` | `critical` |
| `serious` | `high` |
| `moderate` | `medium` |
| `minor` | `low` |

Rules that apply on top of the table, in this precedence order:

1. **Baseline match wins over everything.** A finding whose fingerprint is in
   `qa/baseline.json` is pre-existing: severity is forced to `low`, `status` becomes
   `informational`, and it never blocks the verdict. It stays in the report — it is not
   deleted, hidden, or silently downgraded out of view.
2. **A valid suppression removes the finding** from the gating set. It must carry `target`,
   `reason` and `expires`, and its `scope` must be `third-party`. Missing any part ⇒ invalid
   ⇒ **the check runs and the finding is reported anyway**. Expired ⇒ does not suppress.
   A `rule`-scoped suppression against an a11y rule is always rejected.
3. **A stated acceptance criterion sets a floor of `high`.** When the violated element is the
   subject of an explicit accessibility criterion in the PRD, tech spec or task, the finding
   is at minimum `high` regardless of axe's impact.
4. **Keyboard and focus findings use their own floors**, listed in
   [keyboard-and-focus.md](keyboard-and-focus.md#reporting-these-findings). They have no axe
   impact to map from.
5. **A flaky a11y check is at minimum `medium`** and is never dismissed by a passing retry.
   An axe scan that fails then passes usually means the scan raced the render; the race is
   the finding.

Where axe reports no impact at all (`impact` is optional on both `Result` and `NodeResult`),
default to `moderate` → `medium` and say so in the issue body. Do not guess upward or
downward.

## 2. Node-level impact beats rule-level impact

axe carries an `impact` on the rule result **and** on each node. Use the node's when present:

```python
impact = node.get("impact") or violation.get("impact") or "moderate"
```

This matters because a single rule result can carry nodes of differing severity: the impact
reported for a node comes from the check that actually failed on it, and a rule with several
checks can fail differently on different elements. Reading only `violation.impact` flattens
that distinction and mis-severities the individual fixes.

For reference, the impact levels axe-core 4.12.1 attaches to the rules the fixed tag set runs
most often:

| Impact | Rules (selection) |
|---|---|
| `critical` | `image-alt`, `input-image-alt`, `area-alt`, `label`, `button-name`, `input-button-name`, `select-name`, `aria-required-attr`, `aria-required-children`, `aria-required-parent`, `aria-allowed-attr`, `aria-valid-attr-value`, `aria-roles`, `duplicate-id-aria`, `meta-refresh` |
| `serious` | `color-contrast`, `link-name`, `document-title`, `bypass`, `target-size`, `html-has-lang`, `list`, `listitem`, `nested-interactive`, `aria-hidden-focus`, `aria-command-name`, `aria-input-field-name`, `aria-toggle-field-name`, `frame-title`, `svg-img-alt`, `role-img-alt` |
| `moderate` | `meta-viewport`, `valid-lang`, `html-xml-lang-mismatch`, `form-field-multiple-labels`, `no-autoplay-audio` |
| `minor` | `aria-deprecated-role`, `server-side-image-map` |

Read the impact from the payload rather than from this table — the table is orientation, the
payload is the fact.

## 3. One finding per node, not per rule

A rule failing on five elements is **five findings**, because each element is a separate fix
in a separate place. Never merge them into one issue file. This mirrors the QA Agent's rule
that unrelated problems never share an issue.

## 4. From axe results to the normalized finding

The QA Agent's normalizer (`qa_axe.py`, `normalize_axe_results`) walks
`violations[].nodes[]` and produces one finding dict per node:

| finding key | axe source | notes |
|---|---|---|
| `source` | — | always `"a11y"` |
| `rule` | `violation.id` | e.g. `"color-contrast"`; fingerprint input |
| `name` | `violation.help` | short human title |
| `message` | `node.failureSummary` | falls back to `violation.description` |
| `impact` | `node.impact or violation.impact` | drives the severity table above |
| `target` | `node.target.join(" ")` | the CSS selector path; fingerprint input |
| `file` | resolved from the route or component under scan | falls back to the route URL |
| `line` | `0` | axe has no line numbers; `0` is the contract's "no meaningful line" |
| `helpUrl` | `violation.helpUrl` | carried verbatim into the issue body |
| `expected` | derived from the rule | e.g. "contrast ratio at least 4.5:1" |
| `actual` | parsed from `failureSummary` when present | e.g. "contrast ratio 2.9:1" |
| `reproduce` | the exact command | see below |
| `testId` | `null` for page scans; the Vitest test id for component scans | |
| `statedCriterion` | true when a PRD/spec criterion names this behaviour | sets the `high` floor |

The `node.html` snippet is worth keeping in the issue body — it is what makes an axe finding
actionable without re-running the scan.

### Reproducing commands

Findings are only useful if a human can re-run them. Use the layer's real command:

```bash
# component scan
cd frontend && npm run test -- src/__tests__/user-menu-a11y.test.tsx -t "error state"

# page scan
cd e2e && npx playwright test dashboard-a11y.spec.ts -g "modal open"
```

## 5. Fingerprints and the baseline

The QA Agent fingerprints a finding as:

```
sha256:<hex of f"{source}|{rule}|{normFile}|{normTarget}">
```

For a11y that is `a11y|<axe rule id>|<repo-relative file>|<axe target selector>`. It is
deliberately **line-number-free** so it survives reformatting and line moves. Two
consequences worth designing tests around:

- Changing a selector (renaming a class, restructuring a wrapper) **changes the fingerprint**,
  so a baselined pre-existing violation reappears as newly introduced. That is correct
  behaviour — the markup changed, so the claim "this was already broken here" no longer
  holds. Regenerate the baseline explicitly, with a reason, when a refactor legitimately
  moves a known violation.
- Two different elements failing the same rule produce different fingerprints because
  `target` differs. Baselining one does not baseline the other.

Baseline entries look like:

```json
{
  "fp": "sha256:9f2c...",
  "source": "a11y",
  "rule": "color-contrast",
  "file": "frontend/src/legacy/widget.tsx",
  "target": ".legacy .btn",
  "severity": "medium"
}
```

Regenerating the baseline requires an explicit reason and is never automatic:

```bash
python3 .agents/skills/qa-agent/scripts/qa.py baseline regenerate \
  --reason "axe-core 4.13 changed the target-size spacing exception"
```

## 6. `incomplete[]` — reported as manual, never as pass or fail

`incomplete[]` holds checks axe **could not decide**: contrast over a background image or a
gradient, an element it could not compute, a colour it could not resolve. Treating these as
passes is the single most common way an automated a11y report overclaims.

Handling, in order:

1. Collect every `incomplete[].nodes[]` entry the same way violations are collected
   (`collect_incomplete` in `qa_axe.py`).
2. Emit each as a **manual open item** in `summary.json` under `manualItems[]`, with the rule
   id, the node target, the reason axe gave, and the `helpUrl`:

   ```json
   {
     "criterion": "1.4.3 Contrast (Minimum) — axe rule color-contrast",
     "reason": "incomplete: element has a background image; contrast could not be computed (.hero .cta)"
   }
   ```

3. **Do not** write an `issue_NNN.md` for an incomplete by default. It is not a proven
   failure. It is an unanswered question, and the report must say so.
4. **Do not** count an incomplete toward a pass either. The summary must list it, and the
   coverage numbers must count it as manual, not automated.
5. `a11y.failOnIncomplete: true` in `qa/qa.config.json` flips this for teams that want the
   stricter gate: each incomplete then becomes an issue with severity from the same impact
   table, defaulting to `medium`. It is **off** by default.
6. An incomplete is never a reason to disable the rule that produced it. If contrast cannot
   be computed over a hero image, the answer is a human checking that one element — not
   `disableRules('color-contrast')`.

## 7. Emitting the issue file

Frontmatter keys are exactly `status`, `file`, `line`, `severity`, `author`, `source`, in
that order, no extras and no omissions. Quote any value containing `:` `#` `{` `[` or a
leading `-`/`?`, or the frontmatter stops being valid YAML — axe selectors frequently contain
`:` and `#`.

````markdown
---
status: open
file: frontend/src/components/user-menu.tsx
line: 0
severity: high
author: qa-agent
source: a11y
---

# issue_004 — Menu toggle has no accessible name (button-name)

## Failing assertion

axe rule `button-name` — "Buttons must have discernible text".
Target: `"#user-menu > button.trigger"`

## Observed vs expected

| | |
|---|---|
| Expected | The toggle exposes an accessible name to assistive technology |
| Observed | `<button class="trigger"><svg aria-hidden="true"/></button>` — no text, no `aria-label`, no `aria-labelledby` |

Impact: `serious` → severity `high`.
Help: https://dequeuniversity.com/rules/axe/4.12/button-name

## Reproduce

```bash
cd e2e && npx playwright test dashboard-a11y.spec.ts -g "dashboard route"
```

## Requirement

`FR-9` — tasks/prd-x/prd.md — "every control is operable with a screen reader"

## Suggested fix

Add `aria-label="Open user menu"` to the trigger, or render visually hidden text inside it.
The `svg` stays `aria-hidden="true"`.
````

Note `line: 0`. axe reports selectors, not line numbers; inventing one is worse than
admitting there is none.

## 8. Verdict interaction

- The a11y layer passes when it executed and produced no non-baselined, non-suppressed
  violations, and no keyboard/focus check failed.
- The a11y layer being `skipped-unavailable` does **not** turn the round's verdict into
  `fail` by default, but it sets `complete: false` and populates `skippedLayers[]`, so the
  verdict line reads `PASS — INCOMPLETE (a11y: skipped-unavailable)`.
- `gate.skippedLayers: "fail"` in `qa/qa.config.json` promotes that skip to a hard failure.
  CI configurations should set it.
- Manual items never fail the round on their own. They must appear in `summary.md` and
  `summary.json` so nobody mistakes silence for coverage.
