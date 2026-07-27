# Template — component accessibility test (Vitest + `@testing-library/react` + jest-axe)

Copy into `frontend/src/__tests__/<component>-a11y.test.tsx`. It scans one component across
**every interactive state**, because a component that is accessible when idle and unlabelled
while loading is exactly the defect this layer exists to catch.

Run it with `cd frontend && npm run test`.

```tsx
/**
 * Accessibility — <ComponentName>
 * Requirement: <FR-N> — <path/to/prd.md> — "<criterion text>"
 * Conformance target: WCAG 2.2 Level AA (tags: wcag2a, wcag2aa, wcag22aa)
 *
 * Coverage note: jsdom has no layout engine, so `color-contrast` (SC 1.4.3) and
 * `target-size` (SC 2.5.8) are NOT evaluated here. They are covered by the page
 * scan in e2e/. Nothing in this file disables a rule to hide that gap.
 */
import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axeWcag22 } from "./axe-helpers";
import { UserMenu } from "@/components/user-menu";

describe("UserMenu — accessibility", () => {
  it("has no axe violations in the default state", async () => {
    const { container } = render(<UserMenu user={{ name: "Ada Lovelace" }} />);

    expect(await axeWcag22(container)).toHaveNoViolations();
  });

  it("has no axe violations in the loading state", async () => {
    const { container } = render(<UserMenu user={undefined} isLoading />);

    expect(await axeWcag22(container)).toHaveNoViolations();
  });

  it("has no axe violations in the error state", async () => {
    const { container } = render(
      <UserMenu user={undefined} error="Could not load your profile" />,
    );

    expect(await axeWcag22(container)).toHaveNoViolations();
  });

  it("has no axe violations in the empty state", async () => {
    const { container } = render(<UserMenu user={{ name: "Ada Lovelace" }} items={[]} />);

    expect(await axeWcag22(container)).toHaveNoViolations();
  });

  it("has no axe violations in the disabled state", async () => {
    const { container } = render(<UserMenu user={{ name: "Ada Lovelace" }} disabled />);

    expect(await axeWcag22(container)).toHaveNoViolations();
  });

  it("has no axe violations while the menu is open", async () => {
    const user = userEvent.setup();
    // `baseElement`, not `container`: the menu portals to document.body.
    const { baseElement, getByRole } = render(<UserMenu user={{ name: "Ada Lovelace" }} />);

    await user.click(getByRole("button", { name: /open user menu/i }));

    expect(await axeWcag22(baseElement)).toHaveNoViolations();
  });

  it("has no axe violations after a failed action", async () => {
    const user = userEvent.setup();
    const onSignOut = vi.fn().mockRejectedValue(new Error("network"));
    const { baseElement, getByRole, findByRole } = render(
      <UserMenu user={{ name: "Ada Lovelace" }} onSignOut={onSignOut} />,
    );

    await user.click(getByRole("button", { name: /open user menu/i }));
    await user.click(getByRole("menuitem", { name: /sign out/i }));
    await findByRole("alert");

    expect(await axeWcag22(baseElement)).toHaveNoViolations();
  });
});
```

## What to substitute

| Placeholder | Replace with |
|---|---|
| `<ComponentName>`, `UserMenu` | the component under test |
| `@/components/user-menu` | its import path (`@` maps to `frontend/src`) |
| `<FR-N>` and the criterion text | the requirement this test traces to — a test with no requirement is untraceable coverage |
| the props on each `render` | whatever actually drives that state in your component |
| the six state cases | delete the ones the component genuinely does not have, and **say so in the report** rather than silently dropping them; add any state the component does have (expanded, selected, read-only, dirty, validating) |

## Rules for editing this template

- **Never** replace a failing assertion with a narrower one. If `toHaveNoViolations()` fails,
  the answer is an issue file and a fix, never `axeWcag22(container, { rules: { ... } })`.
- **Never** delete a state case because it fails. A failing loading state is the finding.
- Scan `baseElement` whenever the component renders through a portal — dialogs, menus,
  tooltips, toasts. `container` silently misses portalled content, and a scan that misses
  content reports a false clean.
- If the component under test mocks timers, restore real ones around the scan; axe-core hangs
  on faked `setTimeout`:

  ```tsx
  vi.useRealTimers();
  const results = await axeWcag22(container);
  vi.useFakeTimers();
  ```

- Assertions use the matcher registered in `frontend/src/__tests__/setup.ts`
  (`expect.extend(toHaveNoViolations)`). If the matcher is missing, the failure is a setup
  error — fix the setup, do not switch to `expect(results.violations).toEqual([])` with a
  filter.

## Proving the test can fail

Before this file counts as coverage, verify it fails for the right reason — the same
discipline the QA Agent applies to every generated test. Temporarily break the component (for
example remove the trigger's `aria-label`) and confirm the matching case fails naming
`button-name`. Restore the component afterwards. A scan that cannot fail is worse than no
scan, because it reports safety that does not exist.

## Reproducing a single case

```bash
cd frontend && npm run test -- src/__tests__/user-menu-a11y.test.tsx -t "loading state"
```
