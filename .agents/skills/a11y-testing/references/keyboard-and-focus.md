# Keyboard reachability and focus order — the manual-but-scriptable checks

Reference for [SKILL.md](../SKILL.md) Step 5. These checks run **alongside** the axe scan,
never instead of it, and never after it as an optional extra. axe-core evaluates static DOM
properties; it does not press `Tab`, does not know where focus went, and cannot tell a
keyboard trap from a well-behaved dialog. Everything on this page is invisible to the rule
engine, and most of it is what actually stops a keyboard-only user.

All code is Playwright, written against this repo's `e2e/` project (`baseURL`
`http://localhost:5173`, `testDir` `./`, Chromium). Put these in the same spec as the page
scan so a route is covered by both in one run.

Shared import block for every snippet below:

```ts
import { expect, test } from "@playwright/test";
```

---

## 1. Every interactive element is reachable by Tab (SC 2.1.1)

Walk the tab ring and compare what focus actually visited against what the page exposes as
interactive. Anything interactive that never receives focus is a `critical` finding — it does
not exist for a keyboard user.

```ts
test("every interactive element is reachable by Tab", async ({ page }) => {
  await page.goto("/");

  const interactive = await page.evaluate(() => {
    const selector = [
      "a[href]", "button", "input", "select", "textarea",
      '[tabindex]:not([tabindex="-1"])',
      '[role="button"]', '[role="link"]', '[role="checkbox"]',
      '[role="tab"]', '[role="menuitem"]', '[role="switch"]',
    ].join(",");
    return Array.from(document.querySelectorAll(selector))
      .filter(el => {
        const style = getComputedStyle(el);
        return style.display !== "none"
          && style.visibility !== "hidden"
          && !(el as HTMLElement).hasAttribute("disabled")
          && el.getAttribute("aria-hidden") !== "true";
      })
      .map(el => el.outerHTML.slice(0, 120));
  });

  const visited: string[] = [];
  for (let i = 0; i < interactive.length + 5; i++) {
    await page.keyboard.press("Tab");
    const html = await page.evaluate(
      () => document.activeElement?.outerHTML.slice(0, 120) ?? "",
    );
    if (html && !visited.includes(html)) visited.push(html);
    if (await page.evaluate(() => document.activeElement === document.body)) break;
  }

  const unreachable = interactive.filter(el => !visited.includes(el));
  expect(unreachable, `unreachable by keyboard:\n${unreachable.join("\n")}`).toEqual([]);
});
```

Common causes of a failure here: a `div` with a click handler and no `tabindex`, a custom
control with `tabindex="-1"`, an element hidden behind `pointer-events` tricks, a
`role="button"` on a `span`.

---

## 2. Tab order is sensible and matches visual order (SC 2.4.3, 1.3.2)

Record the focus sequence, then assert it runs top-to-bottom, left-to-right within each row.
A visual order that disagrees with the tab order is disorienting for sighted keyboard users
and for screen-magnifier users.

```ts
test("tab order follows visual order", async ({ page }) => {
  await page.goto("/");

  const positions: Array<{ label: string; x: number; y: number }> = [];
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Tab");
    const stop = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const r = el.getBoundingClientRect();
      return { label: el.getAttribute("aria-label") ?? el.textContent?.trim().slice(0, 40) ?? el.tagName, x: r.x, y: r.y };
    });
    if (!stop) break;
    if (positions.some(p => p.label === stop.label && p.x === stop.x && p.y === stop.y)) break;
    positions.push(stop);
  }

  const outOfOrder = positions.filter((stop, i) => {
    if (i === 0) return false;
    const prev = positions[i - 1];
    const sameRow = Math.abs(stop.y - prev.y) < 8;
    return sameRow ? stop.x < prev.x : stop.y < prev.y;
  });

  expect(outOfOrder, `tab order jumps backwards at: ${outOfOrder.map(s => s.label).join(", ")}`)
    .toEqual([]);
});
```

Also assert the absence of positive `tabindex`, which is the usual root cause:

```ts
test("no positive tabindex", async ({ page }) => {
  await page.goto("/");
  const offenders = await page.$$eval("[tabindex]", els =>
    els.filter(el => Number(el.getAttribute("tabindex")) > 0).map(el => el.outerHTML.slice(0, 120)),
  );
  expect(offenders).toEqual([]);
});
```

---

## 3. The focus indicator is visible (SC 2.4.7)

Compare the computed outline/box-shadow/border of each focused element against its unfocused
state. A rule engine cannot do this; it has no notion of "before focus".

```ts
test("every focus stop has a visible focus indicator", async ({ page }) => {
  await page.goto("/");

  const missing: string[] = [];
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Tab");
    const result = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const s = getComputedStyle(el);
      const hasOutline = s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0;
      const hasShadow = s.boxShadow !== "none";
      const hasBorderChange = parseFloat(s.borderWidth) > 0;
      return {
        label: el.getAttribute("aria-label") ?? el.textContent?.trim().slice(0, 40) ?? el.tagName,
        visible: hasOutline || hasShadow || hasBorderChange,
      };
    });
    if (!result) break;
    if (!result.visible) missing.push(result.label);
  }

  expect(missing, `no visible focus indicator on: ${missing.join(", ")}`).toEqual([]);
});
```

The classic failure is a global `*:focus { outline: none }` with no `:focus-visible`
replacement. Severity: `high` — a keyboard user cannot tell where they are.

---

## 4. No keyboard trap (SC 2.1.2)

Focus must be able to leave every widget, both forwards and backwards, using only the
keyboard. A trap is `critical`: the user cannot continue and cannot escape without a mouse.

```ts
test("no keyboard trap in the page", async ({ page }) => {
  await page.goto("/");

  const seen = new Set<string>();
  let trapped = false;
  let lastLabel = "";

  for (let i = 0; i < 60; i++) {
    await page.keyboard.press("Tab");
    const label = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      return el ? `${el.tagName}:${el.getAttribute("aria-label") ?? el.textContent?.trim().slice(0, 30) ?? ""}` : "";
    });
    if (label && label === lastLabel) { trapped = true; break; }
    lastLabel = label;
    seen.add(label);
  }

  expect(trapped, `focus is stuck on ${lastLabel}`).toBe(false);
  expect(seen.size).toBeGreaterThan(1);

  // Reverse direction must work too.
  await page.keyboard.press("Shift+Tab");
  const back = await page.evaluate(() => document.activeElement?.tagName ?? "");
  expect(back).not.toBe("");
});
```

Note the deliberate exception: a **modal dialog** cycles focus inside itself while open. That
is required behaviour, not a trap, provided `Escape` closes it and focus returns — which is
the next check.

---

## 5. Dialog focus management (SC 2.1.2, 2.4.3, 2.4.11)

Four assertions, all of them invisible to axe: focus moves in, focus is contained, `Escape`
closes, focus returns to the trigger.

```ts
test("dialog moves focus in, traps it while open, and returns it on close", async ({ page }) => {
  await page.goto("/");

  const trigger = page.getByRole("button", { name: "Open settings" });
  await trigger.focus();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  // (a) focus moved into the dialog
  const focusInside = await page.evaluate(() => {
    const d = document.querySelector('[role="dialog"]');
    return !!d && !!document.activeElement && d.contains(document.activeElement);
  });
  expect(focusInside, "focus did not move into the dialog on open").toBe(true);

  // (b) focus stays inside while cycling
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    const stillInside = await page.evaluate(() => {
      const d = document.querySelector('[role="dialog"]');
      return !!d && !!document.activeElement && d.contains(document.activeElement);
    });
    expect(stillInside, `focus escaped the open dialog after ${i + 1} tabs`).toBe(true);
  }

  // (c) Escape closes it
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();

  // (d) focus returned to the trigger
  await expect(trigger).toBeFocused();
});
```

Run the axe page scan **while the dialog is open** as well — see
[../templates/page-a11y.spec.ts.md](../templates/page-a11y.spec.ts.md). The open state is a
different DOM and needs its own scan.

---

## 6. Focus is not obscured (SC 2.4.11, new in WCAG 2.2)

Sticky headers and cookie banners routinely cover the element that just received focus. The
element is focused, axe sees nothing wrong, and the user sees nothing at all.

```ts
test("focused elements are not hidden behind sticky content", async ({ page }) => {
  await page.goto("/");

  const obscured: string[] = [];
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Tab");
    const result = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return { label: el.tagName, hidden: true };
      const cx = r.x + r.width / 2;
      const cy = r.y + r.height / 2;
      const top = document.elementFromPoint(cx, cy);
      const covered = !!top && top !== el && !el.contains(top) && !top.contains(el);
      const offscreen = cy < 0 || cy > window.innerHeight;
      return {
        label: el.getAttribute("aria-label") ?? el.textContent?.trim().slice(0, 40) ?? el.tagName,
        hidden: covered || offscreen,
      };
    });
    if (!result) break;
    if (result.hidden) obscured.push(result.label);
  }

  expect(obscured, `focused but obscured: ${obscured.join(", ")}`).toEqual([]);
});
```

---

## 7. DOM order matches visual order (SC 1.3.2)

A screen reader follows DOM order. CSS `order`, `flex-direction: row-reverse`, `grid-area`
placement and absolute positioning can make the visual order disagree.

```ts
test("DOM order matches visual order in the main landmark", async ({ page }) => {
  await page.goto("/");

  const mismatches = await page.evaluate(() => {
    const nodes = Array.from(document.querySelectorAll("main > *")) as HTMLElement[];
    const boxes = nodes.map(n => ({ tag: n.tagName, y: n.getBoundingClientRect().top }));
    const out: string[] = [];
    for (let i = 1; i < boxes.length; i++) {
      if (boxes[i].y < boxes[i - 1].y - 4) {
        out.push(`${boxes[i - 1].tag} (y=${boxes[i - 1].y}) precedes ${boxes[i].tag} (y=${boxes[i].y}) in the DOM but not visually`);
      }
    }
    return out;
  });

  expect(mismatches).toEqual([]);
});
```

Also flag the CSS properties that cause it, as a cheap static check on the frontend source:
`order:`, `flex-direction: *-reverse`, `grid-auto-flow: dense`, and `position: absolute` on
content-bearing elements.

---

## 8. Skip link (SC 2.4.1)

`bypass` (axe) checks that *a* bypass mechanism exists. It does not check that the skip link
is the first tab stop, becomes visible on focus, or actually moves focus.

```ts
test("skip link is first, visible on focus, and moves focus to main", async ({ page }) => {
  await page.goto("/");

  await page.keyboard.press("Tab");
  const skip = page.locator(":focus");
  await expect(skip).toHaveText(/skip to (main|content)/i);
  await expect(skip).toBeVisible();

  await page.keyboard.press("Enter");

  const landedInMain = await page.evaluate(() => {
    const main = document.querySelector("main, #main, [role='main']");
    const active = document.activeElement;
    return !!main && !!active && (main === active || main.contains(active));
  });
  expect(landedInMain, "activating the skip link did not move focus into main").toBe(true);
});
```

A skip link that is `display: none` until `:focus` is fine. One that stays visually hidden
while focused fails SC 2.4.7 as well.

---

## Reporting these findings

Each failure above becomes an ordinary `source: a11y` issue file, with `rule` set to a stable
identifier for the check rather than an axe rule id — the QA Agent's fingerprint uses
`source|rule|file|target`, so the identifier must be stable across runs:

| Check | `rule` value | Floor severity |
|---|---|---|
| Unreachable interactive element | `keyboard-reachable` | `critical` |
| Keyboard trap | `keyboard-trap` | `critical` |
| Tab order disagrees with visual order | `focus-order` | `high` |
| No visible focus indicator | `focus-visible` | `high` |
| Dialog does not receive focus on open | `dialog-focus-in` | `high` |
| Focus not returned to trigger on close | `dialog-focus-return` | `medium` |
| `Escape` does not close the dialog | `dialog-escape` | `medium` |
| Focus obscured by sticky content | `focus-not-obscured` | `medium` |
| DOM order disagrees with visual order | `dom-order` | `medium` |
| Skip link missing or non-functional | `skip-link` | `medium` |

Escalate above the floor when the affected control is on the critical path of a stated
acceptance criterion — a trap on a checkout button is not the same defect as a trap in a
footer.
