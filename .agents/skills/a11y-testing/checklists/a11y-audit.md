# Accessibility audit — pre-sign-off checklist

Every item answers **yes** or **no**. There is no "mostly", no "n/a" without a written
reason, and no partial credit. A single `no` blocks the sign-off until it is either fixed or
recorded as a finding. Work top to bottom; the sections mirror
[../SKILL.md](../SKILL.md) Steps 1–7.

## Preflight

- [ ] Was the component-layer tooling (`jest-axe` or `vitest-axe`) confirmed present in the frontend manifest before any component scan ran? **yes / no**
- [ ] Was `@axe-core/playwright` confirmed present in the E2E manifest before any page scan ran? **yes / no**
- [ ] Was a headless browser confirmed available before any page scan ran? **yes / no**
- [ ] If any of the above is `no`, was that layer reported as `skipped-unavailable` naming the exact missing package? **yes / no**
- [ ] Was every install proposed to a human and left unexecuted by the agent? **yes / no**

## Configuration

- [ ] Is the tag set exactly `["wcag2a", "wcag2aa", "wcag22aa"]` in every scan? **yes / no**
- [ ] Is `disableRules` absent from every spec, helper and config file? **yes / no**
- [ ] Is `rules: { <id>: { enabled: false } }` absent from every scan option? **yes / no**
- [ ] Is `impactLevels` absent from every `configureAxe` call? **yes / no**
- [ ] Is `resultTypes` absent, so `incomplete[]` is returned in full? **yes / no**
- [ ] Is every `exclude()` selector, if any exists, a third-party widget's own root — never `html`, `body`, `#root`, `*`, or empty? **yes / no**
- [ ] Does every `exclude()` have a recorded suppression carrying `target`, `reason` and `expires`, with `scope: "third-party"`, unexpired? **yes / no**
- [ ] Is the `violations` array asserted whole, with no filtering, slicing or length comparison? **yes / no**

## Component scanning

- [ ] Did the component scan run against the real rendered output, not a static HTML string? **yes / no**
- [ ] Was the **default** state scanned? **yes / no**
- [ ] Was the **loading** state scanned? **yes / no**
- [ ] Was the **error** state scanned? **yes / no**
- [ ] Was the **empty** state scanned? **yes / no**
- [ ] Was the **disabled** state scanned, where the component has one? **yes / no**
- [ ] Was the **open** state scanned, where the component has one (menu, dialog, popover, accordion)? **yes / no**
- [ ] For portalled content, was `baseElement` scanned rather than `container`? **yes / no**
- [ ] Was the harness proven able to fail — a deliberately broken render produces a violation? **yes / no**
- [ ] Does every scan report a non-empty `passes[]`, proving it scanned real content? **yes / no**

## Page scanning

- [ ] Was every primary route in scope scanned? **yes / no**
- [ ] Was each **post-interaction** state scanned after the interaction, not before — modal open, form submitted, validation error shown, empty result set? **yes / no**
- [ ] Were the full results attached to the test run (for example via `testInfo.attach`) so the raw payload including `incomplete[]` is recoverable? **yes / no**
- [ ] Does `results.url` match the route that was meant to be scanned? **yes / no**
- [ ] Were `color-contrast` and `target-size` covered here rather than claimed from a component scan? **yes / no**

## Keyboard and focus (run alongside the axe scan, not instead of it)

- [ ] Is every interactive element reachable by `Tab`? **yes / no**
- [ ] Does the tab order match the visual order, with no positive `tabindex`? **yes / no**
- [ ] Does every focus stop have a visible focus indicator? **yes / no**
- [ ] Is the page free of keyboard traps in both directions (`Tab` and `Shift+Tab`)? **yes / no**
- [ ] Does opening a dialog move focus into it? **yes / no**
- [ ] Does focus stay inside the dialog while it is open? **yes / no**
- [ ] Does `Escape` close the dialog? **yes / no**
- [ ] Does focus return to the trigger when the dialog closes? **yes / no**
- [ ] Is every focused element free of obscuring sticky content (SC 2.4.11)? **yes / no**
- [ ] Does DOM order match visual order in the main landmark? **yes / no**
- [ ] Is a skip link present, the first tab stop, visible on focus, and does it move focus into `main`? **yes / no**

## Severity and findings

- [ ] Was every violation node turned into its own finding — one per node, never one per rule? **yes / no**
- [ ] Was severity assigned from the axe impact table (`critical`→`critical`, `serious`→`high`, `moderate`→`medium`, `minor`→`low`)? **yes / no**
- [ ] Was node-level `impact` preferred over rule-level `impact`? **yes / no**
- [ ] Were findings backing a stated acceptance criterion raised to at least `high`? **yes / no**
- [ ] Were baseline-matched findings forced to `low` / `informational` and left visible in the report? **yes / no**
- [ ] Does every issue file carry frontmatter `status`, `file`, `line`, `severity`, `author`, `source` in that order, with `source: a11y`? **yes / no**
- [ ] Does every issue file carry a reproducing command that actually re-runs that check? **yes / no**
- [ ] Does every a11y issue carry the axe `helpUrl` and the offending HTML snippet? **yes / no**
- [ ] Are selector values containing `:` or `#` quoted so the frontmatter stays valid YAML? **yes / no**

## Incomplete results

- [ ] Was every `incomplete[]` entry collected? **yes / no**
- [ ] Was each reported as a **manual open item**, with rule id, target and reason? **yes / no**
- [ ] Was no incomplete counted as a pass? **yes / no**
- [ ] Was no incomplete counted as a failure (unless `a11y.failOnIncomplete` is explicitly true)? **yes / no**

## Honesty

- [ ] Does the report state that automated scanning covers roughly a third to a half of real accessibility issues? **yes / no**
- [ ] Does the report avoid the words "accessible", "compliant" and "conformant" as claims about the product? **yes / no**
- [ ] Does the report list the routes and states that were **not** reached? **yes / no**
- [ ] Does the report list the four criteria the fixed tag set cannot reach — 1.3.4, 1.3.5, 1.4.12, 2.5.3 — as manual items? **yes / no**
- [ ] Does the report list every other manual criterion that applies to the UI under test? **yes / no**
- [ ] If any layer was skipped, does the verdict line read `PASS — INCOMPLETE (...)` rather than a bare `PASS`? **yes / no**

## Never-weaken

- [ ] Was no test deleted, skipped or `.only`-narrowed in response to a failure? **yes / no**
- [ ] Was no axe rule disabled in response to a failure? **yes / no**
- [ ] Was no `exclude()` broadened in response to a failure? **yes / no**
- [ ] Was no assertion loosened, tolerance widened, or violations array filtered in response to a failure? **yes / no**
- [ ] Was every failure answered with an issue file and nothing else? **yes / no**
