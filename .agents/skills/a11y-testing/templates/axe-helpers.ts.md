# Template — `axe-helpers.ts` (the fixed tag set, in one place)

The tag set `["wcag2a", "wcag2aa", "wcag22aa"]` is fixed by contract. Declaring it once and
importing it everywhere is what makes that enforceable: a reviewer greps one constant instead
of auditing every spec. Two small modules, one per layer, because the frontend and the E2E
project have separate manifests and separate TypeScript configs.

---

## Component layer — `frontend/src/__tests__/axe-helpers.ts`

```ts
/**
 * Shared axe configuration for component-level accessibility scans.
 *
 * Conformance target: WCAG 2.2 Level AA.
 * The tag set is FIXED. Do not add, remove, or reorder tags.
 * Do not add `rules`, `disableRules`, `impactLevels`, or `resultTypes` here —
 * disabling a rule or truncating results is rejected outright.
 */
import { configureAxe } from "jest-axe";
import type { RunOptions } from "axe-core";

export const A11Y_TAGS = ["wcag2a", "wcag2aa", "wcag22aa"] as const;

export const AXE_RUN_OPTIONS: RunOptions = {
  runOnly: { type: "tag", values: [...A11Y_TAGS] },
};

/** Preconfigured axe: every component scan goes through this. */
export const axeWcag22 = configureAxe(AXE_RUN_OPTIONS);

/**
 * jsdom has no layout engine, so `color-contrast` (SC 1.4.3) and `target-size`
 * (SC 2.5.8) cannot be evaluated at this layer. They are covered by the page
 * scan in `e2e/`. Never claim contrast or target-size coverage from a component
 * scan, and never disable them to make the gap go away.
 */
export const COMPONENT_LAYER_GAPS = [
  "1.4.3 Contrast (Minimum) — page layer only",
  "2.5.8 Target Size (Minimum) — page layer only",
] as const;
```

**Substitute:**

- `jest-axe` → `vitest-axe` only if the project already uses it. `vitest-axe` has no
  `configureAxe`; export `AXE_RUN_OPTIONS` alone and pass it at each call site:
  `await axe(container, AXE_RUN_OPTIONS)`.
- `axe-core` types: available transitively through `jest-axe`. If `RunOptions` does not
  resolve, drop the annotation rather than installing `axe-core` directly.

**Do not substitute:** the contents of `A11Y_TAGS`.

---

## Page layer — `e2e/axe-helpers.ts`

```ts
/**
 * Shared axe configuration for page-level accessibility scans.
 *
 * Conformance target: WCAG 2.2 Level AA.
 * The tag set is FIXED. `disableRules()` is never called. `exclude()` is
 * permitted only for a third-party widget's own subtree and only with a
 * recorded suppression carrying target, reason and expiry.
 */
import { AxeBuilder } from "@axe-core/playwright";
import type { Page, TestInfo } from "@playwright/test";
import type { AxeResults } from "axe-core";

export const A11Y_TAGS = ["wcag2a", "wcag2aa", "wcag22aa"] as const;

/** Every page scan starts here. Callers may add `.include()`, nothing else. */
export function axeFor(page: Page): AxeBuilder {
  return new AxeBuilder({ page }).withTags([...A11Y_TAGS]);
}

/**
 * Runs the scan and attaches the raw payload to the test, so the QA Agent's
 * normalizer keeps access to `violations[]`, `incomplete[]` and `passes[]`.
 */
export async function scan(
  page: Page,
  testInfo: TestInfo,
  label: string,
): Promise<AxeResults> {
  const results = await axeFor(page).analyze();

  await testInfo.attach(`axe-${label}`, {
    body: JSON.stringify(results, null, 2),
    contentType: "application/json",
  });

  return results;
}

/**
 * Formats violations so a failing assertion is actionable without re-running.
 * One line per NODE, because one node is one fix.
 */
export function formatViolations(results: AxeResults): string {
  return results.violations
    .flatMap((violation) =>
      violation.nodes.map((node) =>
        [
          `${violation.id} [${node.impact ?? violation.impact ?? "moderate"}]`,
          `  target: ${node.target.join(" ")}`,
          `  html:   ${node.html.slice(0, 160)}`,
          `  help:   ${violation.helpUrl}`,
        ].join("\n"),
      ),
    )
    .join("\n\n");
}

/**
 * `incomplete[]` are checks axe could not decide. They are manual open items —
 * never a pass, never a failure. Callers report these, they do not assert on them.
 */
export function manualItems(results: AxeResults): string[] {
  return results.incomplete.flatMap((entry) =>
    entry.nodes.map(
      (node) =>
        `${entry.id} — ${node.target.join(" ")} — ${entry.help} — ${entry.helpUrl}`,
    ),
  );
}
```

**Substitute:**

- Nothing, in the normal case. Add `.include('#region')` at a call site when a scan should be
  narrowed to a region under test — narrowing with `include` is fine, widening an `exclude`
  is not.

**Verified API notes**

- `AxeBuilder` is exported from `@axe-core/playwright` 4.12.x both as a named export and as
  the default. The named import is used here for clarity.
- `withTags(tags: string | string[])` restricts the run. Calling `options()` or `withRules()`
  afterwards **overrides** it — so neither is called anywhere in this bundle.
- `analyze(): Promise<AxeResults>` where `AxeResults` has `violations`, `incomplete`,
  `passes` and `inapplicable`, each `Result[]` with `id`, `impact?`, `help`, `helpUrl`,
  `tags` and `nodes[]`; each node has `html`, `impact?`, `target` and `failureSummary?`.
- `configureAxe(options)` from `jest-axe` accepts the same object as `axe.run`. It also
  accepts `globalOptions` and `impactLevels`; `impactLevels` is forbidden here because it
  silently discards lower-impact violations.
