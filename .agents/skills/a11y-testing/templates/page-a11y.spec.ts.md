# Template — page accessibility spec (Playwright + `@axe-core/playwright`)

Copy into `e2e/<route>-a11y.spec.ts`. Playwright's `testDir` here is `e2e/` itself, and its
`webServer` block starts both the .NET API on `http://localhost:5080` and the Vite dev server
on `http://localhost:5173`, so no manual server startup is needed.

The spec covers a route **and** its post-interaction states, and runs the keyboard/focus
checks alongside the axe scan — because axe does not press `Tab`.

Run it with `cd e2e && npx playwright test`.

```ts
/**
 * Accessibility — /dashboard
 * Requirement: <FR-N> — <path/to/prd.md> — "<criterion text>"
 * Conformance target: WCAG 2.2 Level AA (tags: wcag2a, wcag2aa, wcag22aa)
 *
 * Honesty note: a clean run here proves that the rules in the fixed tag set found
 * nothing in the states scanned. It is not a conformance claim. Automated scanning
 * covers roughly a third to a half of real accessibility issues.
 */
import { expect, test } from "@playwright/test";
import { formatViolations, manualItems, scan } from "./axe-helpers";

test.describe("/dashboard — accessibility", () => {
  test("route has no automatically detectable WCAG 2.2 A/AA violations", async ({
    page,
  }, testInfo) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();

    const results = await scan(page, testInfo, "dashboard-default");

    // Sanity: a scan that passed nothing scanned nothing.
    expect(results.passes.length).toBeGreaterThan(0);

    // incomplete[] are manual open items — reported, never asserted on.
    for (const item of manualItems(results)) {
      testInfo.annotations.push({ type: "a11y-manual", description: item });
    }

    expect(results.violations, formatViolations(results)).toEqual([]);
  });

  test("modal open state has no automatically detectable violations", async ({
    page,
  }, testInfo) => {
    await page.goto("/dashboard");

    // Drive the interaction FIRST. A scan taken before the modal opens
    // says nothing about the modal.
    await page.getByRole("button", { name: /open settings/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();

    const results = await scan(page, testInfo, "dashboard-modal-open");

    for (const item of manualItems(results)) {
      testInfo.annotations.push({ type: "a11y-manual", description: item });
    }

    expect(results.violations, formatViolations(results)).toEqual([]);
  });

  test("submitted form with validation errors has no automatically detectable violations", async ({
    page,
  }, testInfo) => {
    await page.goto("/dashboard");

    await page.getByRole("button", { name: /save/i }).click();
    await expect(page.getByRole("alert")).toBeVisible();

    const results = await scan(page, testInfo, "dashboard-validation-error");

    for (const item of manualItems(results)) {
      testInfo.annotations.push({ type: "a11y-manual", description: item });
    }

    expect(results.violations, formatViolations(results)).toEqual([]);
  });

  test("empty result set has no automatically detectable violations", async ({
    page,
  }, testInfo) => {
    await page.goto("/dashboard?q=no-such-thing");
    await expect(page.getByText(/no results/i)).toBeVisible();

    const results = await scan(page, testInfo, "dashboard-empty");

    expect(results.violations, formatViolations(results)).toEqual([]);
  });

  /* ---- Keyboard and focus: alongside the scan, never instead of it ---- */

  test("dialog moves focus in, contains it, and returns it on close", async ({ page }) => {
    await page.goto("/dashboard");

    const trigger = page.getByRole("button", { name: /open settings/i });
    await trigger.focus();
    await page.keyboard.press("Enter");

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    const focusInside = await page.evaluate(() => {
      const d = document.querySelector('[role="dialog"]');
      return !!d && !!document.activeElement && d.contains(document.activeElement);
    });
    expect(focusInside, "focus did not move into the dialog on open").toBe(true);

    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("Tab");
      const stillInside = await page.evaluate(() => {
        const d = document.querySelector('[role="dialog"]');
        return !!d && !!document.activeElement && d.contains(document.activeElement);
      });
      expect(stillInside, `focus escaped the open dialog after ${i + 1} tabs`).toBe(true);
    }

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("every focus stop has a visible focus indicator", async ({ page }) => {
    await page.goto("/dashboard");

    const missing: string[] = [];
    for (let i = 0; i < 40; i++) {
      await page.keyboard.press("Tab");
      const result = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || el === document.body) return null;
        const s = getComputedStyle(el);
        const visible =
          (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) ||
          s.boxShadow !== "none";
        return {
          label:
            el.getAttribute("aria-label") ??
            el.textContent?.trim().slice(0, 40) ??
            el.tagName,
          visible,
        };
      });
      if (!result) break;
      if (!result.visible) missing.push(result.label);
    }

    expect(missing, `no visible focus indicator on: ${missing.join(", ")}`).toEqual([]);
  });
});
```

## What to substitute

| Placeholder | Replace with |
|---|---|
| `/dashboard` | the route under audit |
| `<FR-N>` and the criterion text | the requirement this spec traces to |
| the heading / button / alert locators | the real accessible names on your page |
| the four scanned states | the post-interaction states this route actually has; delete what does not apply and **say so in the report**, add what does (drawer open, tab switched, row selected, filter applied, toast shown) |
| the keyboard tests | keep both; add the remaining checks from [../references/keyboard-and-focus.md](../references/keyboard-and-focus.md) — reachability, tab order, keyboard trap, focus not obscured, DOM order, skip link |

## Rules for editing this template

- **Never** call `.disableRules()`, `.withRules()` or `.options()` — the last two override
  `withTags` and silently change the tag set.
- **Never** call `.exclude()` on `html`, `body`, `#root`, `*` or an empty selector. The one
  permitted exclusion is a third-party widget's own root, and only with a recorded
  `scope: "third-party"` suppression carrying `target`, `reason` and `expires`.
- **Never** filter, slice or count the `violations` array before asserting. `toEqual([])` on
  the whole array or nothing.
- **Never** assert on `incomplete[]`. Those are manual open items; annotate and report them.
- Scan **after** the interaction, always. The most common false clean in this layer is a scan
  that ran against the pre-interaction DOM.
- Contrast (SC 1.4.3) and target size (SC 2.5.8) are covered **here** and only here — jsdom
  cannot evaluate either.

## Reproducing a single case

```bash
cd e2e && npx playwright test dashboard-a11y.spec.ts -g "modal open"
```

The attached `axe-dashboard-modal-open` JSON in the Playwright report holds the raw payload,
including `incomplete[]`, for the QA Agent's normalizer.
