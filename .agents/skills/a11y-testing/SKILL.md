---
name: a11y-testing
description: Audits rendered UI against WCAG 2.2 Level AA with axe-core — component scans via jest-axe or vitest-axe across interactive states, page scans via @axe-core/playwright across routes and post-interaction states, and keyboard/focus checks that rule engines cannot automate. Maps axe impact to QA severity and reports incomplete results as manual items. Use when a change touches UI or an accessibility audit is requested. Do not use for visual regression, performance, or non-UI code.
---

# Accessibility Testing (WCAG 2.2 Level AA)

This is the accessibility capability the QA Agent's `a11y` layer delegates to. It scans, it
records, and it hands every violation to the reporting layer as a finding. It never fixes a
failure by weakening the check that found it.

**Read this before anything else.** Automated scanning catches roughly a third to a half of
real accessibility issues. Deque and the GDS accessibility team both put the automated share
in that band. A clean axe run is evidence that a specific set of machine-checkable rules
found nothing — it is **not** evidence of conformance. Report what is proven. Never write
"accessible", "WCAG compliant", or "conformant" in any output produced by this skill.

## Conformance target and fixed configuration

| Setting | Value | Changeable? |
|---|---|---|
| Conformance target | WCAG 2.2 Level AA | No |
| axe tag set | `["wcag2a", "wcag2aa", "wcag22aa"]` | **No — fixed** |
| Rule disabling | Forbidden | No |
| `exclude()` | Third-party widget subtree only, with a recorded suppression | No |

The tag set is fixed by contract. Every scan — component or page — passes exactly these
three tags and nothing else. Do not add `best-practice`. Do not drop `wcag22aa`.

**Consequence you must report honestly.** In axe-core 4.12 the fixed tag set runs 66 of the
73 WCAG-tagged rules. Four rules sit behind tags the fixed set omits and therefore never
run: `autocomplete-valid` (SC 1.3.5), `avoid-inline-spacing` (SC 1.4.12),
`css-orientation-lock` (SC 1.3.4) and `label-content-name-mismatch` (SC 2.5.3). Those four
success criteria move onto the manual list every time. See
[references/wcag22-aa.md](references/wcag22-aa.md).

## Procedures

**Step 1: Preflight — Tooling Detection (Mandatory)**

1. Read the frontend manifest (`frontend/package.json` in this repo) and the E2E manifest
   (`e2e/package.json`). Determine which of these are already installed:
   - component layer: `jest-axe` **or** `vitest-axe`
   - page layer: `@axe-core/playwright`
2. Determine whether a headless browser is usable: `npx playwright --version` succeeds and a
   browser cache exists (`~/Library/Caches/ms-playwright` or `~/.cache/ms-playwright`).
3. **If the tooling for a layer is absent, stop that layer immediately.** Report status
   `skipped-unavailable` and name the **exact** missing packages, for example:
   `a11y component scan: skipped-unavailable — jest-axe is not installed in frontend/`
   `a11y page scan: skipped-unavailable — @axe-core/playwright is not installed in e2e/`
4. **Never install anything.** Adding a dependency is a human decision. Propose the exact
   command from [references/axe-setup.md](references/axe-setup.md) and stop.
5. When neither layer is available, the whole a11y layer is `skipped-unavailable`. A skipped
   layer never counts toward a pass — the verdict line must read
   `PASS — INCOMPLETE (a11y: skipped-unavailable)`, never a bare `PASS`.
6. Do NOT skip this step. Running a scan with tooling you assumed was present produces a
   false clean report, which is worse than no report.

**Step 2: Scope the Audit (Mandatory)**

1. Collect every in-scope file that touches UI — `.tsx`, `.jsx`, `.css`, `.html` and, on a
   .NET frontend, `.cshtml`/`.razor`. Any such file in scope makes this layer **required**.
2. For each in-scope component, list the routes that render it. In this repo, routes are
   declared in `frontend/src/App.tsx` and served from `http://localhost:5173`.
3. For each component, enumerate its **interactive states**: default, loading, error, empty,
   disabled, and open (menu, dialog, popover, accordion, combobox).
4. For each route, enumerate its **post-interaction states**: modal open, form submitted,
   validation error shown, filtered/empty result set, expanded navigation.
5. Write the enumeration down. It is the audit's coverage claim, and Step 7 reports what it
   did **not** reach.

**Step 3: Component Scanning (Mandatory)**

1. Component scans run under Vitest with `@testing-library/react`, in the project's existing
   test directory (`frontend/src/__tests__/` here). Copy
   [templates/component-a11y.test.tsx.md](templates/component-a11y.test.tsx.md).
2. Centralize the fixed tag set in one helper module rather than repeating it per test —
   see [templates/axe-helpers.ts.md](templates/axe-helpers.ts.md).
3. Scan **every state enumerated in Step 2.4**, one assertion per state, not just the happy
   path. A component that is accessible when idle and unlabelled while loading is a defect
   this layer exists to catch.
4. Scan the element that RTL returns as `container`. When the component renders through a
   React portal (dialogs, tooltips, toasts), scan `baseElement` instead — the portal content
   is not inside `container`.
5. Know the jsdom limits and state them rather than working around them: jsdom has no layout
   engine, so `color-contrast` and `target-size` cannot be evaluated at this layer. They are
   covered by Step 4, never by disabling them. See
   [references/axe-setup.md](references/axe-setup.md).
6. Run: `cd frontend && npm run test`.

**Step 4: Page Scanning (Mandatory)**

1. Page scans run under Playwright with `@axe-core/playwright`, in the project's E2E
   directory (`e2e/` here, `baseURL` `http://localhost:5173`). Copy
   [templates/page-a11y.spec.ts.md](templates/page-a11y.spec.ts.md).
2. Scan every primary route from Step 2.2 **and** every post-interaction state from
   Step 2.4. Drive the interaction with Playwright first, then analyze — a scan taken before
   the modal opens says nothing about the modal.
3. Attach the full results JSON to the test via `testInfo.attach` so the QA Agent's
   normalizer has the raw payload, including `incomplete[]`.
4. Assert on `violations` being empty. Do not filter the array before asserting.
5. Run: `cd e2e && npx playwright test`.

**Step 5: Keyboard and Focus Checks (Mandatory)**

Automated rule engines do not evaluate focus order, focus movement, or keyboard traps.
These checks run **alongside** the axe scan, in the same Playwright spec, never instead of
it. Full code for each is in
[references/keyboard-and-focus.md](references/keyboard-and-focus.md).

1. Every interactive element is reachable by `Tab` in an order that matches the visual
   order (SC 2.1.1, 2.4.3).
2. The focused element always has a visible focus indicator (SC 2.4.7).
3. No keyboard trap: focus can always move forward and backward out of any widget
   (SC 2.1.2).
4. Opening a dialog moves focus into it; closing it returns focus to the trigger; `Escape`
   closes it (SC 2.1.2, 2.4.3, 2.4.11).
5. DOM order matches visual order — no positive `tabindex`, no CSS reordering that desyncs
   reading order from tab order (SC 1.3.2, 2.4.3).
6. A skip link is present, reachable as the first tab stop, and moves focus to the main
   landmark (SC 2.4.1).
7. Report each of these as a normal finding when it fails. A keyboard trap is `critical`
   regardless of what axe reported.

**Step 6: Severity Mapping and Incomplete Handling (Mandatory)**

1. Map every violation node to a severity by axe impact. Full rules, including the baseline
   and flake interactions, are in
   [references/severity-mapping.md](references/severity-mapping.md).

   | axe impact | severity |
   |---|---|
   | `critical` | `critical` |
   | `serious` | `high` |
   | `moderate` | `medium` |
   | `minor` | `low` |

2. One finding per **node**, not per rule. A rule that fails on five elements is five
   findings, because each is a separate fix.
3. `incomplete[]` entries — the checks axe could not decide — are reported as **manual open
   items**. They are never counted as a pass and never counted as a failure, unless the QA
   configuration sets `a11y.failOnIncomplete` to true.
4. A failure of a manual keyboard/focus check from Step 5 carries the severity of its
   impact on a keyboard-only user, floor `high` when it blocks task completion.

**Step 7: Reporting (Mandatory)**

1. Emit one `issue_NNN.md` per finding in the QA Agent's issue format, with frontmatter
   `status`, `file`, `line`, `severity`, `author`, `source` in that order and
   `source: a11y`. Carry the axe `helpUrl` into the body.
2. Give every issue a reproducing command a human can paste:
   `cd frontend && npm run test -- src/__tests__/foo.test.tsx -t "error state has no axe violations"`
   `cd e2e && npx playwright test dashboard-a11y.spec.ts -g "modal open"`
3. State the coverage honestly, in these terms:
   - which routes and states were scanned, and which were not reached;
   - which success criteria are on the manual list (including the four the fixed tag set
     cannot reach);
   - the `incomplete[]` items awaiting human judgement;
   - the sentence **"Automated scanning covers roughly a third to a half of real
     accessibility issues; this report proves only what the listed rules checked."**
4. Never write a conformance claim. "No automatically detectable WCAG 2.2 A/AA violations in
   the scanned states" is the strongest statement this skill is allowed to make.

## Rule disabling and broad excludes are REJECTED

This section is not advisory. These patterns are rejected on sight, in generated tests, in
review, and in any fix proposed in response to a failure. The only permitted response to a
violation is a finding.

**Never write this — rule disabling:**

```ts
// REJECTED. Disabling the rule deletes the evidence, not the barrier.
new AxeBuilder({ page }).withTags(TAGS).disableRules('color-contrast');

// REJECTED. Same thing through axe run options.
await axe(container, { rules: { 'aria-required-children': { enabled: false } } });

// REJECTED. Same thing hidden in a shared helper.
const axe = configureAxe({ rules: { region: { enabled: false } } });

// REJECTED. impactLevels silently drops moderate and minor violations.
const axe = configureAxe({ impactLevels: ['critical'] });

// REJECTED. resultTypes truncates incomplete[], which must be reported as manual items.
await axe(container, { resultTypes: ['violations'] });
```

**Never write this — broad excludes:**

```ts
// REJECTED. Every one of these excludes the entire page or app subtree.
new AxeBuilder({ page }).exclude('html');
new AxeBuilder({ page }).exclude('body');
new AxeBuilder({ page }).exclude('#root');
new AxeBuilder({ page }).exclude('*');
new AxeBuilder({ page }).exclude('');
```

**Never write this — asserting around the failure:**

```ts
// REJECTED. Filtering the violations array is rule disabling with extra steps.
expect(results.violations.filter(v => v.impact === 'critical')).toEqual([]);
expect(results.violations.length).toBeLessThan(5);

// REJECTED. A skipped a11y test reports safety that does not exist.
test.skip('dashboard has no axe violations', async () => { /* ... */ });
```

**The one permitted exclusion.** A third-party widget's own subtree may be excluded when the
markup is not yours to fix, and only with a recorded suppression carrying all three parts:

```json
{
  "id": "sup-001",
  "target": "a11y:aria-required-children:frontend/src/vendor/date-picker.tsx",
  "reason": "third-party date picker; upstream issue vendor/dp#412",
  "expires": "2026-12-31",
  "scope": "third-party",
  "addedBy": "gustavo",
  "addedAt": "2026-07-25"
}
```

```ts
// Permitted only with the suppression above on file. The selector targets the vendor
// widget's own root, never a container that also holds first-party markup.
const results = await new AxeBuilder({ page })
  .withTags(A11Y_TAGS)
  .exclude('[data-vendor="acme-date-picker"]')
  .analyze();
```

A suppression missing `target`, `reason` or `expires` is invalid, and **the check runs
anyway**. An expired suppression does not suppress. A `rule`-scoped suppression against an
a11y rule is always rejected — there is no valid way to turn an axe rule off.

## Honesty requirement

Repeat, in the report and to the user:

- Automated accessibility scanning catches roughly **a third to a half** of real
  accessibility issues.
- axe finds violations of machine-checkable rules. It cannot judge whether alt text is
  *meaningful*, whether a heading structure is *logical*, whether an error message is
  *actionable*, or whether a flow is *usable* with a screen reader.
- The output of this skill is evidence, not a certificate. Only "no automatically detectable
  violations in the states scanned" is claimable.
- Real conformance needs assistive-technology testing and disabled users in research. Say so
  whenever someone reads this report as a sign-off.

## Files in this bundle

- [references/axe-setup.md](references/axe-setup.md) — adding the tooling to a Vitest +
  Playwright project, jsdom caveats, wiring the fixed tag set.
- [references/wcag22-aa.md](references/wcag22-aa.md) — WCAG 2.2 A and AA criteria by POUR,
  what axe automates, what is inherently manual, and the criteria new in 2.2.
- [references/keyboard-and-focus.md](references/keyboard-and-focus.md) — the
  manual-but-scriptable checks, with Playwright code for each.
- [references/severity-mapping.md](references/severity-mapping.md) — axe impact to severity,
  how findings become issue files, how `incomplete[]` is handled.
- [checklists/a11y-audit.md](checklists/a11y-audit.md) — binary pre-sign-off checklist.
- [templates/component-a11y.test.tsx.md](templates/component-a11y.test.tsx.md) — component
  test covering multiple interactive states.
- [templates/page-a11y.spec.ts.md](templates/page-a11y.spec.ts.md) — Playwright spec covering
  a route and a post-interaction state.
- [templates/axe-helpers.ts.md](templates/axe-helpers.ts.md) — the shared fixed tag set.
- [examples/component-scan.md](examples/component-scan.md) — narrated component scan turned
  into issue files.
- [examples/page-scan.md](examples/page-scan.md) — narrated page scan turned into issue
  files.

## Error Handling

- **axe tooling absent.** Report `skipped-unavailable` and name the exact missing packages
  and the manifest they are missing from (`jest-axe` in `frontend/package.json`,
  `@axe-core/playwright` in `e2e/package.json`). Propose the install command from
  [references/axe-setup.md](references/axe-setup.md) and stop. Never run `npm install`. Never
  substitute a hand-rolled DOM check and present it as an axe scan.
- **No headless browser.** When `npx playwright --version` fails or no browser cache exists,
  the page layer is `skipped-unavailable` with reason
  `"no headless browser (run: cd e2e && npx playwright install --with-deps chromium)"`. The
  component layer still runs — report it alone and mark the page layer skipped. Do not
  downgrade a page-level finding to a component-level one to fill the gap.
- **Route requires authentication.** Do not embed credentials in a spec, a fixture, or a
  finding. Use a Playwright storage state or a session fixture the project already provides
  and read secrets from the environment. When no such fixture exists, mark the route
  `manual` with reason `"route requires authentication; no session fixture available"` and
  report it as an open item — never as a pass, never as a skip that disappears from the
  summary.
- **Violation in third-party markup.** Do not exclude it on your own authority. Emit the
  finding with the vendor selector in `target` and a note identifying the owner. An exclusion
  becomes permitted only after a `scope: "third-party"` suppression with `target`, `reason`
  and `expires` is recorded and validated. If the vendor markup is interleaved with your own
  (the vendor renders your children), no exclusion is possible — report the finding.
- **axe `incomplete[]` results.** These are checks axe could not decide, usually contrast
  over an image or a gradient, or an element it could not compute. Report each as a manual
  open item with the rule id, the node target and the help URL. Never count an incomplete as
  a pass. Never count it as a violation. Only `a11y.failOnIncomplete: true` in the QA
  configuration changes that, and it is off by default.
- **Scan throws or times out.** Record the layer as `failed` with the captured stderr, not
  as passed. axe-core hangs when timers are mocked — if a component test mocks timers,
  restore real timers around the scan rather than removing the scan.
- **Zero violations reported.** Verify the scan actually ran against rendered content
  (non-empty `passes[]`, a `url`/container that matches the target). A scan of an empty
  container returns zero violations and proves nothing.
