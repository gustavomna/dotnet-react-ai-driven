# WCAG 2.2 Level A and AA — what axe automates, what stays manual

Reference for [SKILL.md](../SKILL.md) Steps 2, 6 and 7. The conformance target is **WCAG 2.2
Level AA**: 31 Level A criteria plus 24 Level AA criteria, 55 in total. WCAG 2.2 is
backwards-compatible with 2.1 and 2.0, so meeting 2.2 AA means meeting every A and AA
criterion from all three versions. WCAG 2.2 also **removed** SC 4.1.1 Parsing — do not report
against it.

Rule names below are axe-core rule ids as of axe-core **4.12.1**, taken from the engine's own
rule metadata. Column meanings:

- **axe rules** — the rules that fire for that criterion under the fixed tag set.
- **Coverage** — `automated` (axe decides it), `partial` (axe catches a subset; a human must
  judge the rest), `manual` (no axe rule exists; a human or a scripted keyboard check).

---

## The fixed tag set and the four rules it cannot reach

The tag set is fixed at `["wcag2a", "wcag2aa", "wcag22aa"]`. In axe-core 4.12.1 that runs 66
of the 73 WCAG-tagged rules. Three of the seven it skips are Level AAA and correctly out of
scope. The other four are Level A/AA rules that sit behind the `wcag21a` / `wcag21aa` tags,
which the fixed set omits:

| axe rule | Criterion | Level | Effect |
|---|---|---|---|
| `autocomplete-valid` | 1.3.5 Identify Input Purpose | AA | Never runs — 1.3.5 moves to manual |
| `avoid-inline-spacing` | 1.4.12 Text Spacing | AA | Never runs — 1.4.12 moves to manual |
| `css-orientation-lock` | 1.3.4 Orientation | AA | Never runs (also `experimental`) — 1.3.4 moves to manual |
| `label-content-name-mismatch` | 2.5.3 Label in Name | A | Never runs (also `experimental`) — 2.5.3 moves to manual |

**Do not "fix" this by adding tags.** The tag set is fixed by contract so that every project
under the QA Agent produces comparable results. The correct response is to report those four
criteria as manual items in every audit, using the manual checks described below. This is
part of the honesty requirement, not a footnote.

The three deliberately skipped Level AAA rules are `color-contrast-enhanced` (1.4.6),
`meta-refresh-no-exceptions` (2.2.4/3.2.5) and `identical-links-same-purpose` (2.4.9).

---

## Perceivable

| SC | Name | Level | axe rules | Coverage |
|---|---|---|---|---|
| 1.1.1 | Non-text Content | A | `image-alt`, `input-image-alt`, `object-alt`, `role-img-alt`, `svg-img-alt`, `area-alt`, `aria-meter-name`, `aria-progressbar-name` | partial |
| 1.2.1 | Audio-only and Video-only (Prerecorded) | A | — | manual |
| 1.2.2 | Captions (Prerecorded) | A | `video-caption` | partial |
| 1.2.3 | Audio Description or Media Alternative | A | — | manual |
| 1.2.4 | Captions (Live) | AA | — | manual |
| 1.2.5 | Audio Description (Prerecorded) | AA | — | manual |
| 1.3.1 | Info and Relationships | A | `list`, `listitem`, `definition-list`, `dlitem`, `aria-required-children`, `aria-required-parent`, `td-headers-attr`, `th-has-data-cells`, `td-has-header`, `table-fake-caption`, `p-as-heading`, `aria-hidden-body` | partial |
| 1.3.2 | Meaningful Sequence | A | — | manual (see [keyboard-and-focus.md](keyboard-and-focus.md)) |
| 1.3.3 | Sensory Characteristics | A | — | manual |
| 1.3.4 | Orientation | AA | `css-orientation-lock` — **not run under the fixed tag set** | manual |
| 1.3.5 | Identify Input Purpose | AA | `autocomplete-valid` — **not run under the fixed tag set** | manual |
| 1.4.1 | Use of Color | A | `link-in-text-block` | partial |
| 1.4.2 | Audio Control | A | `no-autoplay-audio` | partial |
| 1.4.3 | Contrast (Minimum) | AA | `color-contrast` | partial — **page layer only**, jsdom cannot compute it |
| 1.4.4 | Resize Text | AA | `meta-viewport` | partial |
| 1.4.5 | Images of Text | AA | — | manual |
| 1.4.10 | Reflow | AA | — | manual (script it: see below) |
| 1.4.11 | Non-text Contrast | AA | — | manual |
| 1.4.12 | Text Spacing | AA | `avoid-inline-spacing` — **not run under the fixed tag set** | manual |
| 1.4.13 | Content on Hover or Focus | AA | — | manual |

**Manual checks worth scripting.**

- *1.3.2 Meaningful Sequence* — read the DOM order and compare against the visual order; a
  Playwright bounding-box comparison catches CSS reordering. Code in
  [keyboard-and-focus.md](keyboard-and-focus.md).
- *1.3.4 Orientation* — resize the viewport to portrait and landscape and assert the content
  is usable in both: `await page.setViewportSize({ width: 360, height: 800 })` and the
  transpose.
- *1.3.5 Identify Input Purpose* — assert `autocomplete` attributes on inputs collecting user
  data: `expect(page.getByLabel('Email')).toHaveAttribute('autocomplete', 'email')`.
- *1.4.4 / 1.4.10 Resize and Reflow* — set the viewport to 320 CSS px wide (or 1280 at 400 %
  zoom) and assert no horizontal scrollbar:
  `expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)`.
- *1.4.12 Text Spacing* — inject the WCAG text-spacing overrides (line-height 1.5, paragraph
  spacing 2 em, letter spacing 0.12 em, word spacing 0.16 em) via `page.addStyleTag` and
  assert nothing is clipped or overlapping.
- *1.4.13 Content on Hover or Focus* — hover a tooltip trigger, assert the tooltip is
  dismissible with `Escape`, hoverable (moving the pointer onto it does not dismiss it), and
  persistent until dismissed.

---

## Operable

| SC | Name | Level | axe rules | Coverage |
|---|---|---|---|---|
| 2.1.1 | Keyboard | A | `frame-focusable-content`, `scrollable-region-focusable`, `server-side-image-map` | partial — keyboard walk required |
| 2.1.2 | No Keyboard Trap | A | — | manual (scripted) |
| 2.1.4 | Character Key Shortcuts | A | — | manual |
| 2.2.1 | Timing Adjustable | A | `meta-refresh` | partial |
| 2.2.2 | Pause, Stop, Hide | A | `blink`, `marquee` | partial |
| 2.3.1 | Three Flashes or Below Threshold | A | — | manual |
| 2.4.1 | Bypass Blocks | A | `bypass` | partial — skip-link behaviour is scripted |
| 2.4.2 | Page Titled | A | `document-title` | automated |
| 2.4.3 | Focus Order | A | — | manual (scripted) |
| 2.4.4 | Link Purpose (In Context) | A | `link-name`, `area-alt` | partial |
| 2.4.5 | Multiple Ways | AA | — | manual |
| 2.4.6 | Headings and Labels | AA | — | manual (axe checks presence, not descriptiveness) |
| 2.4.7 | Focus Visible | AA | — | manual (scripted) |
| 2.4.11 | Focus Not Obscured (Minimum) | AA | — | manual (scripted) — **new in 2.2** |
| 2.5.1 | Pointer Gestures | A | — | manual |
| 2.5.2 | Pointer Cancellation | A | — | manual |
| 2.5.3 | Label in Name | A | `label-content-name-mismatch` — **not run under the fixed tag set** | manual |
| 2.5.4 | Motion Actuation | A | — | manual |
| 2.5.7 | Dragging Movements | AA | — | manual — **new in 2.2** |
| 2.5.8 | Target Size (Minimum) | AA | `target-size` | partial — **page layer only**, needs box geometry |

`target-size` is the **only** axe rule carried by the `wcag22aa` tag. Dropping that tag would
remove the engine's entire WCAG 2.2 contribution, which is why the tag set is fixed.

---

## Understandable

| SC | Name | Level | axe rules | Coverage |
|---|---|---|---|---|
| 3.1.1 | Language of Page | A | `html-has-lang`, `html-lang-valid`, `html-xml-lang-mismatch` | automated |
| 3.1.2 | Language of Parts | AA | `valid-lang` | partial |
| 3.2.1 | On Focus | A | — | manual |
| 3.2.2 | On Input | A | — | manual |
| 3.2.3 | Consistent Navigation | AA | — | manual (cross-page) |
| 3.2.4 | Consistent Identification | AA | — | manual (cross-page) |
| 3.2.6 | Consistent Help | A | — | manual — **new in 2.2** |
| 3.3.1 | Error Identification | A | — | manual |
| 3.3.2 | Labels or Instructions | A | `label`, `form-field-multiple-labels` | partial |
| 3.3.3 | Error Suggestion | AA | — | manual |
| 3.3.4 | Error Prevention (Legal, Financial, Data) | AA | — | manual |
| 3.3.7 | Redundant Entry | A | — | manual — **new in 2.2** |
| 3.3.8 | Accessible Authentication (Minimum) | AA | — | manual — **new in 2.2** |

---

## Robust

| SC | Name | Level | axe rules | Coverage |
|---|---|---|---|---|
| 4.1.2 | Name, Role, Value | A | `button-name`, `input-button-name`, `link-name`, `select-name`, `summary-name`, `aria-command-name`, `aria-input-field-name`, `aria-toggle-field-name`, `aria-tab-name`, `aria-tooltip-name`, `aria-roles`, `aria-allowed-attr`, `aria-required-attr`, `aria-valid-attr`, `aria-valid-attr-value`, `aria-prohibited-attr`, `aria-conditional-attr`, `aria-deprecated-role`, `aria-braille-equivalent`, `aria-roledescription`, `aria-hidden-focus`, `nested-interactive`, `duplicate-id-aria`, `frame-title`, `frame-title-unique`, `label`, `area-alt`, `input-image-alt` | partial — the densest automated area |
| 4.1.3 | Status Messages | AA | — | manual |

*4.1.1 Parsing was removed in WCAG 2.2.* Do not report it, and do not carry it in a baseline.

---

## The criteria new in WCAG 2.2 — how to check each

Six of the nine additions are relevant here. Note the levels carefully: **2.4.12 and 2.4.13
are Level AAA and therefore outside the AA conformance target** — check them as advisory,
report them as `low`, and never gate on them.

### 2.4.11 Focus Not Obscured (Minimum) — AA

*When a component receives keyboard focus, it is not entirely hidden by author-created
content.* Sticky headers, cookie banners and floating action bars are the usual offenders.

Automated? No axe rule. Scripted check: tab through the page and assert the focused element's
bounding box is not fully covered — the `elementFromPoint` version is in
[keyboard-and-focus.md](keyboard-and-focus.md).

```ts
const box = await page.locator(":focus").boundingBox();
const covered = await page.evaluate(([x, y]) => {
  const top = document.elementFromPoint(x, y);
  return !top?.matches(":focus, :focus *") && !top?.contains(document.activeElement);
}, [box!.x + box!.width / 2, box!.y + box!.height / 2]);
expect(covered).toBe(false);
```

### 2.4.12 Focus Not Obscured (Enhanced) — **AAA, advisory only**

*No part of the focused component is hidden.* Same check as 2.4.11 but over the whole
bounding box rather than a point. Report as advisory `low`; it is not part of AA.

### 2.4.13 Focus Appearance — **AAA, advisory only**

*The focus indicator is at least as large as a 2 CSS px perimeter of the component and has a
contrast ratio of at least 3:1 against adjacent colours.* Requires pixel measurement of the
indicator; no engine automates it. Advisory `low` at AA. **The AA obligation for focus
indication is 2.4.7 Focus Visible** — that one is mandatory and is the scripted check in
[keyboard-and-focus.md](keyboard-and-focus.md).

### 2.5.7 Dragging Movements — AA

*Any function operated by dragging has a single-pointer alternative that does not require
dragging, unless dragging is essential.* Sliders, reorderable lists, kanban boards, map pans,
signature pads.

Automated? No. Manual/scripted check: for each drag interaction, assert an equivalent
non-drag path exists — arrow keys on a slider, a "move up / move down" control on a
reorderable list, a numeric input beside the handle.

```ts
await page.getByRole("slider", { name: "Volume" }).focus();
await page.keyboard.press("ArrowRight");
await expect(page.getByRole("slider", { name: "Volume" })).toHaveAttribute("aria-valuenow", "51");
```

If the only way to change a value is `page.mouse.down()` → `move` → `up`, that is a
`high`-severity finding.

### 2.5.8 Target Size (Minimum) — AA

*Pointer targets are at least 24 by 24 CSS px, unless spaced, inline, essential, or
UA-controlled.*

Automated? Yes — `target-size`, the only `wcag22aa` axe rule. It runs in the **page** layer
only; jsdom has no box geometry, so a component scan cannot see it. axe applies the spacing
exception itself, so hand-auditing on top is rarely needed; verify axe's `incomplete[]` for
targets it could not measure.

### 3.2.6 Consistent Help — Level **A**

*When a help mechanism (contact details, a help link, a chat widget, self-help) appears on
multiple pages, it appears in the same relative order on each.*

Automated? No. Cross-page manual check: list the routes that offer help, and assert the help
affordance sits at the same position in the DOM order relative to its siblings on each.

```ts
for (const route of ["/", "/dashboard", "/settings"]) {
  await page.goto(route);
  const links = await page.getByRole("link").allInnerTexts();
  expect(links.indexOf("Help")).toBe(links.length - 1); // same relative position everywhere
}
```

### 3.3.7 Redundant Entry — Level **A**

*Information previously entered by the user in the same process is auto-populated or
available to select, unless re-entry is essential (for example, a password confirmation).*

Automated? No. Scripted check on multi-step flows: fill step 1, advance, go back, assert the
values survived; or advance to a step that asks for the same data and assert it is
pre-filled or offered.

```ts
await page.getByLabel("Email").fill("user@example.com");
await page.getByRole("button", { name: "Next" }).click();
await page.getByRole("button", { name: "Back" }).click();
await expect(page.getByLabel("Email")).toHaveValue("user@example.com");
```

### 3.3.8 Accessible Authentication (Minimum) — AA

*No cognitive function test (remembering a password, solving a puzzle, transcribing
characters) is required for any step of authentication, unless an alternative or a mechanism
to assist exists.*

Automated? No. Manual check on the auth flow:

- password fields allow paste and password-manager autofill — no `onpaste` blocking, no
  `autocomplete="off"` on `current-password`/`new-password`;
- no image or puzzle CAPTCHA without an object-recognition or personal-content alternative;
- no "type characters 3, 7 and 9 of your memorable word";
- email-link or WebAuthn alternatives count as the mechanism.

```ts
const password = page.getByLabel("Password");
await expect(password).toHaveAttribute("autocomplete", /current-password|new-password/);
expect(await password.evaluate(el => el.getAttribute("onpaste"))).toBeNull();
```

---

## Using this reference in a report

For each audited route or component, produce three lists:

1. **Proven** — criteria whose axe rules ran and passed, named by rule id.
2. **Manual** — every `manual` row above that applies to the UI under test, plus the four
   criteria the fixed tag set cannot reach (1.3.4, 1.3.5, 1.4.12, 2.5.3), plus every
   `incomplete[]` entry from the scan.
3. **Not reached** — states and routes the audit did not visit.

A criterion never appears in list 1 because nothing failed. It appears there only when a rule
that covers it actually executed.
