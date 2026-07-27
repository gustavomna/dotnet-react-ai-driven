# Worked example — a page scan, end to end

A narrated run of [SKILL.md](../SKILL.md) Steps 1, 2, 4, 5, 6 and 7 against a route served by
this repository's frontend. It shows a scan of a route and of a post-interaction state, an
`incomplete[]` result handled as a manual item, a baseline-matched pre-existing violation, and
a keyboard finding that axe could never produce.

**Scenario.** The same change ships a `/dashboard` route with a settings dialog and a search
filter. Round `003` is open and already holds `issue_001` and `issue_002` from
[component-scan.md](component-scan.md), so numbering continues at `issue_003`.

---

## Step 1 — Preflight

Preflight emits nothing. The a11y layer announces itself only when a command is about to run,
or when it turns out there is nothing to run — so the checks below happen silently.

`e2e/package.json` lists `@axe-core/playwright`, and `npx playwright --version` succeeds with
a Chromium cache present, so the page layer runs. Playwright's `webServer` block starts the
.NET API on `http://localhost:5080` and Vite on `http://localhost:5173` — `baseURL` is
`http://localhost:5173`.

Had the browser binary been missing, `detect` would have reported it under `runtimes`:

```json
"headlessBrowser": {
  "available": false,
  "detail": "playwright CLI found but no browsers cache (run: npx playwright install)"
}
```

and every browser-bound target would have been dropped before execution, so the page scan
reports a skip rather than a failure — the code is not broken, the runtime is missing:

```
[qa] layer=a11y status=skipped-unavailable reason="no headless browser available (playwright CLI found but no browsers cache (run: npx playwright install))"
```

Component scans do not need a browser, so a mixed a11y layer keeps running its `vitest-axe`
targets and only the page half is dropped. The unit and integration layers still run. Because a
skipped layer never counts toward a pass, the verdict line reads
`PASS — INCOMPLETE (a11y: skipped-unavailable)` — never a bare `PASS`.

## Step 2 — Enumerate routes and post-interaction states

| # | State | How it is reached |
|---|---|---|
| 1 | `/dashboard` default | `page.goto("/dashboard")` |
| 2 | settings modal open | click "Open settings" |
| 3 | validation error shown | click "Save" with an empty required field |
| 4 | empty result set | `?q=no-such-thing` |

Alongside these, the keyboard checks from
[../references/keyboard-and-focus.md](../references/keyboard-and-focus.md) run in the same
spec.

## Step 4/5 — Run the spec

The spec follows [../templates/page-a11y.spec.ts.md](../templates/page-a11y.spec.ts.md):
`scan()` from `e2e/axe-helpers.ts`, tags fixed, results attached, `violations` asserted whole.

The a11y layer is the e2e runner narrowed by the `a11y` filename filter that stack detection
records, so `dashboard-a11y.spec.ts` is in the layer by virtue of its name:

```
[qa] layer=a11y status=running command="npx playwright test a11y" cwd=e2e
```

```bash
cd e2e && npx playwright test a11y
```

```
Running 6 tests using 1 worker

  ✓  1 dashboard-a11y.spec.ts:14:3 › route has no automatically detectable WCAG 2.2 A/AA violations (1.2s)
  ✘  2 dashboard-a11y.spec.ts:33:3 › modal open state has no automatically detectable violations (1.6s)
  ✓  3 dashboard-a11y.spec.ts:52:3 › submitted form with validation errors ... (1.4s)
  ✓  4 dashboard-a11y.spec.ts:70:3 › empty result set ... (0.9s)
  ✘  5 dashboard-a11y.spec.ts:84:3 › dialog moves focus in, contains it, and returns it on close (1.1s)
  ✓  6 dashboard-a11y.spec.ts:118:3 › every focus stop has a visible focus indicator (2.3s)

  2 failed
```

The axe failure, with the message `formatViolations` produced:

```
  2) dashboard-a11y.spec.ts:33:3 › modal open state has no automatically detectable violations

    Error: expect(received).toEqual(expected)

    target-size [serious]
      target: [role="dialog"] .toolbar button.icon-only
      html:   <button class="icon-only" aria-label="Bold"><svg aria-hidden="true"/></button>
      help:   https://dequeuniversity.com/rules/axe/4.12/target-size

    aria-hidden-focus [serious]
      target: #app-backdrop
      html:   <div id="app-backdrop" aria-hidden="true"><button class="close">×</button></div>
      help:   https://dequeuniversity.com/rules/axe/4.12/aria-hidden-focus

    meta-viewport [moderate]
      target: meta[name="viewport"]
      html:   <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
      help:   https://dequeuniversity.com/rules/axe/4.12/meta-viewport
```

And the keyboard failure, which no rule engine can produce:

```
  5) dashboard-a11y.spec.ts:84:3 › dialog moves focus in, contains it, and returns it on close

    Error: expect(locator).toBeFocused()

    Locator:  getByRole('button', { name: /open settings/i })
    Expected: focused
    Received: not focused
    Call log: after Escape, document.activeElement was <body>
```

The layer closed with:

```
[qa] layer=a11y status=failed exit=1 duration=9.8s failures=2
```

## Step 6 — Normalize, baseline, and map severity

`scan()` attached the raw results, so Playwright wrote them to
`test-results/dashboard-a11y-modal-open-state/axe-dashboard-modal-open.json`. That path matches
the first entry of `a11y.resultsGlob` (default
`["test-results/**/axe-*.json", "**/qa-axe-*.json", "**/axe-results*.json"]`), so the a11y layer
recorded it in `axeArtifacts[]` and `report` ingested it with no flag. A payload written
somewhere those globs do not reach is handed over explicitly instead — `--axe` is repeatable:

```bash
python3 .agents/skills/qa-agent/scripts/qa.py report --round 3 \
  --axe test-results/dashboard/axe-dashboard-modal-open.json
```

Either route runs the same normalizer: one finding per `violations[].nodes[]` entry, impact
mapped `critical` → `critical`, `serious` → `high`, `moderate` → `medium`, `minor` → `low`, and
every `incomplete[]` entry turned into a `manualItems` row in `summary.json` rather than a
failure.

The attached `axe-dashboard-modal-open` payload, trimmed:

```json
{
  "url": "http://localhost:5173/dashboard",
  "testEngine": { "name": "axe-core", "version": "4.12.1" },
  "violations": [
    { "id": "target-size", "impact": "serious",
      "help": "Touch targets must have sufficient size and space",
      "helpUrl": "https://dequeuniversity.com/rules/axe/4.12/target-size",
      "tags": ["cat.sensory-and-visual-cues", "wcag22aa", "wcag258"],
      "nodes": [{ "impact": "serious",
        "target": ["[role=\"dialog\"] .toolbar button.icon-only"],
        "html": "<button class=\"icon-only\" aria-label=\"Bold\"><svg aria-hidden=\"true\"/></button>",
        "failureSummary": "Fix any of the following:\n  Target has insufficient size (20px by 20px, should be at least 24px by 24px)" }] },

    { "id": "aria-hidden-focus", "impact": "serious",
      "help": "aria-hidden elements must not be focusable or contain focusable elements",
      "helpUrl": "https://dequeuniversity.com/rules/axe/4.12/aria-hidden-focus",
      "tags": ["cat.name-role-value", "wcag2a", "wcag412"],
      "nodes": [{ "impact": "serious", "target": ["#app-backdrop"],
        "html": "<div id=\"app-backdrop\" aria-hidden=\"true\"><button class=\"close\">×</button></div>",
        "failureSummary": "Fix all of the following:\n  Focusable content should have tabindex='-1' or be removed from the DOM" }] },

    { "id": "meta-viewport", "impact": "moderate",
      "help": "Zooming and scaling must not be disabled",
      "helpUrl": "https://dequeuniversity.com/rules/axe/4.12/meta-viewport",
      "tags": ["cat.sensory-and-visual-cues", "wcag2aa", "wcag144"],
      "nodes": [{ "impact": "moderate", "target": ["meta[name=\"viewport\"]"],
        "html": "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, maximum-scale=1\">",
        "failureSummary": "Fix any of the following:\n  maximum-scale on <meta> tag disables zooming on mobile devices" }] }
  ],
  "incomplete": [
    { "id": "color-contrast", "impact": "serious",
      "help": "Elements must meet minimum color contrast ratio thresholds",
      "helpUrl": "https://dequeuniversity.com/rules/axe/4.12/color-contrast",
      "nodes": [{ "target": [".hero .cta"],
        "html": "<a class=\"cta\" href=\"/start\">Get started</a>",
        "any": [{ "id": "color-contrast", "message": "Element's background color could not be determined because it is overlapped by another element" }] }] }
  ],
  "passes": [ /* 58 rules */ ]
}
```

### Baseline comparison

`qa/baseline.json` already carries one of these — the viewport meta predates this change:

```json
{ "fp": "sha256:4be1…", "source": "a11y", "rule": "meta-viewport",
  "file": "/dashboard", "target": "meta[name=\"viewport\"]", "severity": "medium" }
```

The fingerprint is `sha256(a11y|meta-viewport|/dashboard|meta[name="viewport"])`, so the
finding matches and is forced to `low` / `informational`. It stays visible in the report — it is
not deleted, and it does not block.

Note the `file` value: for a page scan it is the route **path**, not the full URL the browser
visited. An absolute URL is reduced to its path before it reaches the fingerprint, so the same
page baselined against `http://localhost:5173/dashboard` in development still matches when CI
serves it from `http://127.0.0.1:4173/dashboard`. A component scan uses the component's source
path instead, which is why `component-scan.md`'s baseline entries are keyed on `.tsx` files.

### The mapping

| Finding | Source | Impact | Baseline? | Severity | Status |
|---|---|---|---|---|---|
| `target-size` on the dialog toolbar button | a11y | `serious` | no | **`high`** | open |
| `aria-hidden-focus` on `#app-backdrop` | a11y | `serious` | no | **`high`** | open |
| `meta-viewport` `maximum-scale=1` | a11y | `moderate` | **yes** | **`low`** | informational |
| Focus not returned to trigger on close | a11y (keyboard) | — | no | **`medium`** | open |
| `color-contrast` on `.hero .cta` | a11y | — | — | — | **manual item** |

Four findings, one manual item. Note `target-size` is the single rule the `wcag22aa` tag
contributes — dropping that tag would have hidden this violation entirely, which is why the
tag set is fixed.

## Step 7 — The issue files

`qa/rounds/003/issue_003.md`:

````markdown
---
status: open
file: frontend/src/components/settings-dialog.tsx
line: 0
severity: high
author: qa-agent
source: a11y
---

# issue_003 — Dialog toolbar buttons are 20×20 px, below the 24×24 minimum (target-size)

## Failing assertion

axe rule `target-size` — "Touch targets must have sufficient size and space".
Target: `"[role=\"dialog\"] .toolbar button.icon-only"`
Node impact: `serious` → severity `high`. WCAG 2.2 SC 2.5.8 (Level AA, new in 2.2).

## Observed vs expected

| | |
|---|---|
| Expected | Pointer targets are at least 24×24 CSS px, or spaced so a 24 px circle does not overlap a neighbour |
| Observed | `<button class="icon-only" aria-label="Bold"><svg aria-hidden="true"/></button>` measures 20×20 px with 2 px gaps |

Help: https://dequeuniversity.com/rules/axe/4.12/target-size

## Reproduce

```bash
cd e2e && npx playwright test dashboard-a11y.spec.ts -g "modal open"
```

## Requirement

`FR-12` — tasks/prd-dashboard/prd.md — "the settings dialog is usable on touch devices"

## Suggested fix

`settings-dialog.tsx` sizes the toolbar buttons with `h-5 w-5`. Raise the hit area to
`h-6 w-6` (24 px) while keeping the icon at 20 px, or add padding so the button's box reaches
24×24. Increasing the gap between buttons to 24 px would also satisfy the spacing exception,
but enlarging the target is the better fix.
````

`qa/rounds/003/issue_004.md`:

````markdown
---
status: open
file: frontend/src/components/app-backdrop.tsx
line: 0
severity: high
author: qa-agent
source: a11y
---

# issue_004 — Focusable close button inside an aria-hidden backdrop (aria-hidden-focus)

## Failing assertion

axe rule `aria-hidden-focus` — "aria-hidden elements must not be focusable or contain focusable elements".
Target: `"#app-backdrop"`
Node impact: `serious` → severity `high`.

## Observed vs expected

| | |
|---|---|
| Expected | Content hidden from assistive technology is also removed from the tab order |
| Observed | `<div id="app-backdrop" aria-hidden="true"><button class="close">×</button></div>` — the close button is reachable by Tab but invisible to a screen reader, so a keyboard user lands on a control that is never announced |

Help: https://dequeuniversity.com/rules/axe/4.12/aria-hidden-focus

## Reproduce

```bash
cd e2e && npx playwright test dashboard-a11y.spec.ts -g "modal open"
```

## Requirement

`FR-12` — tasks/prd-dashboard/prd.md — "the settings dialog is usable on touch devices"

## Suggested fix

The backdrop should not own a control. Move the close button into the dialog itself, where it
is announced and where the dialog's focus containment applies. If the backdrop must keep a
click-to-dismiss affordance, make it a non-focusable `div` with an `onClick` and rely on the
dialog's own `Escape` handler for keyboard users.
````

`qa/rounds/003/issue_005.md`:

````markdown
---
status: open
file: frontend/src/components/settings-dialog.tsx
line: 0
severity: medium
author: qa-agent
source: a11y
---

# issue_005 — Focus is not returned to the trigger when the settings dialog closes

## Failing assertion

Keyboard/focus check `dialog-focus-return` (no axe rule covers this).
`await expect(page.getByRole('button', { name: /open settings/i })).toBeFocused()` — after
`Escape`, `document.activeElement` was `<body>`.

## Observed vs expected

| | |
|---|---|
| Expected | Closing the dialog returns focus to the control that opened it (SC 2.4.3) |
| Observed | Focus is dropped to `<body>`; the next `Tab` restarts at the top of the page, so a keyboard user loses their place entirely |

The dialog passed the other three checks: focus moved in on open, stayed contained while open,
and `Escape` closed it.

## Reproduce

```bash
cd e2e && npx playwright test dashboard-a11y.spec.ts -g "dialog moves focus in"
```

## Requirement

`FR-12` — tasks/prd-dashboard/prd.md — "the settings dialog is usable on touch devices"

## Suggested fix

`settings-dialog.tsx` unmounts the dialog without restoring focus. Capture
`document.activeElement` when the dialog opens and call `.focus()` on it in the close handler
after the dialog unmounts, or delegate focus management to a dialog primitive that implements
`onCloseAutoFocus`.
````

The baseline-matched `meta-viewport` finding is recorded as `issue_006` with
`status: informational` and `severity: low`. It appears in the summary and blocks nothing.

## What the summary records

`summary.json` covers the **whole round**, not just this page scan — so the counts below
include `issue_001` (`critical`) and `issue_002` (`high`) from
[component-scan.md](component-scan.md) alongside this scan's four findings.

```json
{
  "round": 3,
  "verdict": "fail",
  "complete": true,
  "counts": { "critical": 1, "high": 3, "medium": 1, "low": 1, "total": 6 },
  "manualItems": [
    { "criterion": "1.4.3 Contrast (Minimum) — axe rule color-contrast",
      "reason": "incomplete: background color could not be determined because the element is overlapped (.hero .cta)" },
    { "criterion": "1.3.4 Orientation",
      "reason": "axe rule css-orientation-lock is outside the fixed tag set" },
    { "criterion": "1.3.5 Identify Input Purpose",
      "reason": "axe rule autocomplete-valid is outside the fixed tag set" },
    { "criterion": "1.4.12 Text Spacing",
      "reason": "axe rule avoid-inline-spacing is outside the fixed tag set" },
    { "criterion": "2.5.3 Label in Name",
      "reason": "axe rule label-content-name-mismatch is outside the fixed tag set" },
    { "criterion": "2.5.7 Dragging Movements",
      "reason": "no automated rule exists; the dashboard has a reorderable widget list requiring a human check" }
  ],
  "baseline": { "used": true, "preexisting": 1, "introduced": 3 },
  "coverage": { "criteria": 55, "automated": 33, "manual": 22, "uncovered": 0 }
}
```

The `color-contrast` incomplete is **not** an issue file and **not** a pass. It is an open
question, and it sits in `manualItems` until a human looks at `.hero .cta` over its
background image.

## What was deliberately not done

- `.disableRules('target-size')` was not added, even though `target-size` is the newest and
  noisiest rule in the set.
- `.exclude('#app-backdrop')` was not added to make `aria-hidden-focus` go away. An exclusion
  is permitted only for a third-party widget's own subtree, with a recorded
  `scope: "third-party"` suppression carrying `target`, `reason` and `expires`.
  `#app-backdrop` is first-party markup, so no suppression could ever be valid for it.
- The `color-contrast` incomplete was not resolved by asserting `violations` only and
  quietly dropping `incomplete`.
- The failing focus-return test was not deleted, and `maximum-scale=1` was not left
  unreported just because it is pre-existing.

## Honesty statement carried into the report

> Four automatically detectable WCAG 2.2 A/AA violations and one keyboard-behaviour defect
> were found across four states of `/dashboard`; one further violation is pre-existing and
> recorded as informational. Automated scanning covers roughly a third to a half of real
> accessibility issues. This report proves only what the 66 rules in the fixed tag set
> checked, in Chromium, in the four states listed. One `incomplete` result and 22 criteria
> remain manual, including all four criteria the fixed tag set cannot reach. No screen reader
> was used, and no disabled user tested this interface. This is not a conformance claim.
