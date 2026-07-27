# Worked example — a component scan, end to end

A narrated run of [SKILL.md](../SKILL.md) Steps 1, 2, 3, 6 and 7 against a real component in
this repository's frontend. It shows the tooling check, the state enumeration, the actual axe
output, and the issue files that output becomes.

**Scenario.** A change adds `frontend/src/components/user-menu.tsx` — an avatar button that
opens a menu, with a loading skeleton and an error state. The QA Agent has resolved the scope,
found a `.tsx` file in it, and therefore made the a11y layer required. Round `003` is open.

---

## Step 1 — Preflight

Preflight emits nothing. The a11y layer announces itself only when a command is about to run,
or when it turns out there is nothing to run — so the reading below happens silently.

Read `frontend/package.json`:

```jsonc
"devDependencies": {
  "@testing-library/react": "^16.3.2",
  "jest-axe": "^10.0.0",          // present -> component layer available
  "vitest": "^4.1.4"
}
```

`jest-axe` is present, so the component layer runs. Had it been missing, the layer would have
been reported unavailable instead of run:

```
[qa] layer=a11y status=skipped-unavailable reason="axe tooling not installed (vitest-axe or jest-axe, @axe-core/playwright)"
```

and nothing would have been installed. The remedy —
`cd frontend && npm install --save-dev jest-axe @types/jest-axe` — is reported in the summary
for a human to run, never executed by the agent.

## Step 2 — Enumerate the states

Reading `user-menu.tsx` gives six reachable states. This list is the coverage claim:

| State | Trigger |
|---|---|
| default | `user` provided, menu closed |
| loading | `isLoading` true |
| error | `error` string provided |
| empty | `items` is `[]` |
| disabled | `disabled` true |
| open | trigger activated — content portals to `document.body` |

## Step 3 — Write and run the scan

The test follows
[../templates/component-a11y.test.tsx.md](../templates/component-a11y.test.tsx.md) exactly:
one case per state, `baseElement` for the portalled open state, tags fixed via
`axeWcag22` from `frontend/src/__tests__/axe-helpers.ts`.

The a11y layer is the unit runner narrowed by the `a11y` filename filter that stack detection
records, so the file name `user-menu-a11y.test.tsx` is what puts this test in the layer:

```
[qa] layer=a11y status=running command="npm run test -- --run a11y" cwd=frontend
```

```bash
cd frontend && npm run test -- --run a11y
```

```
 ❯ src/__tests__/user-menu-a11y.test.tsx (7 tests | 2 failed) 1284ms
   ✓ UserMenu — accessibility > has no axe violations in the default state
   × UserMenu — accessibility > has no axe violations in the loading state
   ✓ UserMenu — accessibility > has no axe violations in the error state
   ✓ UserMenu — accessibility > has no axe violations in the empty state
   ✓ UserMenu — accessibility > has no axe violations in the disabled state
   × UserMenu — accessibility > has no axe violations while the menu is open
   ✓ UserMenu — accessibility > has no axe violations after a failed action

 FAIL  src/__tests__/user-menu-a11y.test.tsx > has no axe violations in the loading state
 Error: expect(received).toHaveNoViolations(expected)

 Expected the HTML found at $('div > div[role="progressbar"]') to have no violations:

 <div role="progressbar" class="h-8 w-8 animate-spin"></div>

 Received:

 "ARIA progressbar nodes must have an accessible name (aria-progressbar-name)"

 Fix any of the following:
   Element does not have text that is visible to screen readers
   aria-label attribute does not exist or is empty
   aria-labelledby attribute does not exist, references elements that do not exist
     or references elements that are empty

 You can find more information on this issue here:
 https://dequeuniversity.com/rules/axe/4.12/aria-progressbar-name
```

The second failure, from the open state:

```
 FAIL  src/__tests__/user-menu-a11y.test.tsx > has no axe violations while the menu is open
 Error: expect(received).toHaveNoViolations(expected)

 Expected the HTML found at $('#user-menu > button.trigger') to have no violations:

 <button class="trigger"><svg aria-hidden="true" viewBox="0 0 24 24"></svg></button>

 Received:

 "Buttons must have discernible text (button-name)"
 ...
 https://dequeuniversity.com/rules/axe/4.12/button-name
```

The layer closed with:

```
[qa] layer=a11y status=failed exit=1 duration=2.6s failures=2
```

Note the *open* state caught the unnamed trigger while the *default* state did not: the
default render never focused or expanded the control, and the failing node lives in the
portalled subtree that only `baseElement` reaches. This is the reason Step 2 exists.

## Step 6 — Normalize and map severity

`jest-axe` returns the payload in process, so it reaches the report by one of two routes. If
the test writes it beside the run as `qa-axe-user-menu.json`, it matches `**/qa-axe-*.json` in
`a11y.resultsGlob` (default
`["test-results/**/axe-*.json", "**/qa-axe-*.json", "**/axe-results*.json"]`), the a11y layer
records it in `axeArtifacts[]`, and `report` picks it up with no flag. Otherwise it is handed
over explicitly:

```bash
python3 .agents/skills/qa-agent/scripts/qa.py report --round 3 --axe qa-axe-user-menu.json
```

`--axe` is repeatable. Either route runs the same normalizer: one finding per
`violations[].nodes[]` entry, impact mapped `critical` → `critical`, `serious` → `high`,
`moderate` → `medium`, `minor` → `low`, and every `incomplete[]` entry turned into a
`manualItems` row in `summary.json` rather than a failure.

The raw payload behind those two failures, trimmed to what the normalizer uses:

```json
{
  "violations": [
    {
      "id": "aria-progressbar-name",
      "impact": "serious",
      "help": "ARIA progressbar nodes must have an accessible name",
      "helpUrl": "https://dequeuniversity.com/rules/axe/4.12/aria-progressbar-name",
      "tags": ["cat.aria", "wcag2a", "wcag412"],
      "nodes": [
        {
          "impact": "serious",
          "target": ["div > div[role=\"progressbar\"]"],
          "html": "<div role=\"progressbar\" class=\"h-8 w-8 animate-spin\"></div>",
          "failureSummary": "Fix any of the following:\n  Element does not have text that is visible to screen readers\n  aria-label attribute does not exist or is empty"
        }
      ]
    },
    {
      "id": "button-name",
      "impact": "critical",
      "help": "Buttons must have discernible text",
      "helpUrl": "https://dequeuniversity.com/rules/axe/4.12/button-name",
      "tags": ["cat.name-role-value", "wcag2a", "wcag412", "section508"],
      "nodes": [
        {
          "impact": "critical",
          "target": ["#user-menu > button.trigger"],
          "html": "<button class=\"trigger\"><svg aria-hidden=\"true\" viewBox=\"0 0 24 24\"></svg></button>",
          "failureSummary": "Fix any of the following:\n  Element does not have inner text that is visible to screen readers\n  aria-label attribute does not exist or is empty"
        }
      ]
    }
  ],
  "incomplete": [],
  "passes": [ /* 41 rules */ ]
}
```

Applying the mapping from
[../references/severity-mapping.md](../references/severity-mapping.md):

| Rule | Node impact | Severity | Why |
|---|---|---|---|
| `button-name` | `critical` | **`critical`** | direct impact mapping |
| `aria-progressbar-name` | `serious` | **`high`** | direct impact mapping |

Two nodes, two findings. `incomplete[]` is empty here — contrast is not evaluated in jsdom at
all, so there is nothing to defer. `passes.length` is 41, confirming the scan ran against real
content rather than an empty container.

## Step 7 — The issue files

`qa/rounds/003/issue_001.md`:

````markdown
---
status: open
file: frontend/src/components/user-menu.tsx
line: 0
severity: critical
author: qa-agent
source: a11y
---

# issue_001 — Menu trigger has no accessible name (button-name)

## Failing assertion

axe rule `button-name` — "Buttons must have discernible text".
Target: `"#user-menu > button.trigger"`
Node impact: `critical` → severity `critical`.

## Observed vs expected

| | |
|---|---|
| Expected | The trigger exposes an accessible name to assistive technology |
| Observed | `<button class="trigger"><svg aria-hidden="true" viewBox="0 0 24 24"></svg></button>` — no inner text, no `aria-label`, no `aria-labelledby` |

Help: https://dequeuniversity.com/rules/axe/4.12/button-name

## Reproduce

```bash
cd frontend && npm run test -- src/__tests__/user-menu-a11y.test.tsx -t "while the menu is open"
```

## Requirement

`FR-9` — tasks/prd-user-menu/prd.md — "every control in the header is operable with a screen reader"

## Suggested fix

`user-menu.tsx` renders the trigger with an icon only. Add `aria-label="Open user menu"` to
the `<button>`, or render a visually hidden `<span>` with the label inside it. Keep the `svg`
`aria-hidden="true"` so the name is not announced twice.
````

`qa/rounds/003/issue_002.md`:

````markdown
---
status: open
file: frontend/src/components/user-menu.tsx
line: 0
severity: high
author: qa-agent
source: a11y
---

# issue_002 — Loading spinner has no accessible name (aria-progressbar-name)

## Failing assertion

axe rule `aria-progressbar-name` — "ARIA progressbar nodes must have an accessible name".
Target: `"div > div[role=\"progressbar\"]"`
Node impact: `serious` → severity `high`.

## Observed vs expected

| | |
|---|---|
| Expected | The busy indicator announces what is loading |
| Observed | `<div role="progressbar" class="h-8 w-8 animate-spin"></div>` — role with no name; a screen reader announces "progress bar" and nothing else |

Help: https://dequeuniversity.com/rules/axe/4.12/aria-progressbar-name

## Reproduce

```bash
cd frontend && npm run test -- src/__tests__/user-menu-a11y.test.tsx -t "loading state"
```

## Requirement

`FR-9` — tasks/prd-user-menu/prd.md — "every control in the header is operable with a screen reader"

## Suggested fix

Add `aria-label="Loading your profile"` to the `role="progressbar"` element. If the spinner is
purely decorative because adjacent visible text already announces the wait, drop the
`progressbar` role and mark it `aria-hidden="true"` instead — but do not leave a named role
with no name.
````

## What the summary records

```json
{
  "counts": { "critical": 1, "high": 1, "medium": 0, "low": 0, "total": 2 },
  "issues": [
    { "id": "issue_001", "file": "frontend/src/components/user-menu.tsx", "line": 0,
      "severity": "critical", "source": "a11y", "status": "open",
      "title": "Menu trigger has no accessible name (button-name)" },
    { "id": "issue_002", "file": "frontend/src/components/user-menu.tsx", "line": 0,
      "severity": "high", "source": "a11y", "status": "open",
      "title": "Loading spinner has no accessible name (aria-progressbar-name)" }
  ],
  "manualItems": [
    { "criterion": "1.4.3 Contrast (Minimum)",
      "reason": "not evaluable in jsdom; covered by the page scan in e2e/" },
    { "criterion": "2.5.8 Target Size (Minimum)",
      "reason": "not evaluable in jsdom; covered by the page scan in e2e/" },
    { "criterion": "1.3.5 Identify Input Purpose",
      "reason": "axe rule autocomplete-valid is outside the fixed tag set" },
    { "criterion": "2.5.3 Label in Name",
      "reason": "axe rule label-content-name-mismatch is outside the fixed tag set" }
  ]
}
```

## What was deliberately not done

- The `aria-progressbar-name` failure was **not** answered with
  `axeWcag22(container, { rules: { 'aria-progressbar-name': { enabled: false } } })`.
- The failing loading-state case was **not** deleted, and no `test.skip` was added.
- The assertion was **not** narrowed to
  `expect(results.violations.filter(v => v.impact === 'critical')).toEqual([])`, which would
  have hidden `issue_002` while still looking green.

The only response to a failure is an issue file.

## Honesty statement carried into the report

> Two automatically detectable WCAG 2.2 A/AA violations were found across six rendered states
> of `UserMenu`. Automated scanning covers roughly a third to a half of real accessibility
> issues; this report proves only what the 66 rules in the fixed tag set checked, in jsdom,
> where contrast and target size cannot be evaluated. Criteria 1.3.4, 1.3.5, 1.4.12 and 2.5.3
> remain manual. Screen-reader behaviour, the meaningfulness of labels, and the usability of
> the menu for keyboard-only users were not verified by this layer.
