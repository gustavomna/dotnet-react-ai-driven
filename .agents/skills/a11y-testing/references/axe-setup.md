# axe setup for a Vitest + Playwright project

Reference for [SKILL.md](../SKILL.md) Steps 1, 3 and 4. Everything here is grounded in this
repository's real stack: React 19, Vite 8, Vitest 4 with jsdom, `@testing-library/react`,
Playwright with `baseURL` `http://localhost:5173`, and a .NET 10 API on
`http://localhost:5080`.

## 1. The agent proposes, a human installs

> **The agent never runs these commands.** Adding a dependency is a human decision. When
> tooling is missing, print the relevant block, say which manifest it is missing from, and
> stop. This is a suggestion for a human to run — nothing in this skill may execute it.

**Suggested for a human to run — component layer** (into `frontend/`):

```bash
cd frontend
npm install --save-dev jest-axe @types/jest-axe
```

**Suggested for a human to run — page layer** (into `e2e/`):

```bash
cd e2e
npm install --save-dev @axe-core/playwright
npx playwright install --with-deps chromium
```

That is the whole install. Verified package facts as of writing:

| Package | Latest | Notes |
|---|---|---|
| `jest-axe` | `10.0.0` | CommonJS, no bundled types, depends on `axe-core` 4.10.x, `engines.node >= 16` |
| `@types/jest-axe` | community | Needed for TypeScript; see the Vitest augmentation below |
| `@axe-core/playwright` | `4.12.1` | Dual CJS/ESM, ships its own types, depends on `axe-core` ~4.12.x, peer `playwright-core >= 1.0.0` |
| `axe-core` | `4.12.1` | Pulled in transitively; do not install it directly unless you need `axe.run` yourself |
| `vitest-axe` | `0.1.0` (`latest`), `1.0.0-pre.5` (`pre`) | Alternative to `jest-axe`; see below |

### jest-axe or vitest-axe?

Both are thin wrappers over the same `axe-core`. The choice is about matcher plumbing, not
about coverage.

- **`jest-axe` — the default recommendation for this repo.** Its `toHaveNoViolations` is a
  plain matcher object, so `expect.extend(toHaveNoViolations)` works unchanged under Vitest.
  It is actively released (10.0.0) and its stable line tracks current `axe-core`.
- **`vitest-axe` — use it when the project already has it.** Its stable release is `0.1.0`
  with a peer range of `vitest >= 0.16.0`, which predates Vitest 1.0; on Vitest 4 npm may
  warn or require `--legacy-peer-deps`. The `1.0.0-pre.5` prerelease adds the
  `vitest-axe/matchers` and `vitest-axe/extend-expect` subpath exports. Do not migrate a
  project from one to the other as part of an audit — that is a dependency change, and it is
  a human decision.

Import shapes, both verified:

```ts
// jest-axe (CommonJS, interop-imported by Vitest)
import { axe, configureAxe, toHaveNoViolations } from "jest-axe";

// vitest-axe (>= 1.0.0-pre)
import { axe } from "vitest-axe";
import * as axeMatchers from "vitest-axe/matchers";
// or, to extend expect implicitly:
import "vitest-axe/extend-expect";
```

## 2. Wiring the fixed tag set

The tag set is `["wcag2a", "wcag2aa", "wcag22aa"]` and it is fixed. Put it in exactly one
module and import it everywhere — see
[../templates/axe-helpers.ts.md](../templates/axe-helpers.ts.md).

**Component layer.** axe-core's `runOnly` option restricts the run to a tag list:

```ts
const options = { runOnly: { type: "tag" as const, values: ["wcag2a", "wcag2aa", "wcag22aa"] } };

// per call
const results = await axe(container, options);

// or bake it into a preconfigured axe (jest-axe)
const axeWcag22 = configureAxe(options);
const results = await axeWcag22(container);
```

`configureAxe` accepts the same options object as `axe.run`, plus `globalOptions` (passed to
`axe.configure`) and `impactLevels`. **Do not use `impactLevels`** — it silently discards
violations below the chosen level, which is rule disabling under another name.

**Page layer.** `AxeBuilder#withTags` is the equivalent:

```ts
import { AxeBuilder } from "@axe-core/playwright";

const results = await new AxeBuilder({ page })
  .withTags(["wcag2a", "wcag2aa", "wcag22aa"])
  .analyze();
```

`AxeBuilder` is exported both as a named export and as the default export in 4.12.x. Prefer
the named import — older examples that use `import AxeBuilder from '@axe-core/playwright'`
still work but are less explicit.

Order matters on the builder: `options()`, `withRules()` and `withTags()` override each
other, last call wins. Call `withTags` and never call `options()` or `withRules()` after it.

## 3. jsdom caveats for component scanning

jsdom has no layout or rendering engine. Two consequences, and neither is a reason to
disable anything:

1. **`color-contrast` (SC 1.4.3) cannot run under jsdom.** `jest-axe` turns it off for that
   reason — it needs computed colors from a real renderer. Contrast is covered by the
   **page** scan in Playwright, which runs in Chromium. Never assert contrast at the
   component layer, and never claim contrast coverage from a component scan.
2. **`target-size` (SC 2.5.8) needs box geometry** that jsdom does not compute. Same
   resolution: it is a page-layer check.

Further jsdom notes:

- **The `region` rule does not apply here.** It is tagged `best-practice` only, so the fixed
  tag set never runs it. The widely copied advice to disable `region` when testing isolated
  components is unnecessary with this configuration — and disabling a rule is forbidden
  regardless. If you ever do want landmark structure covered, render the component inside a
  real `<main>` wrapper instead of turning a rule off.
- **React portals escape `container`.** RTL's `container` holds only the component's own
  subtree. Dialogs, tooltips and toasts that portal to `document.body` must be scanned via
  `baseElement`:

  ```ts
  const { container, baseElement } = render(<Dialog open />);
  const results = await axe(baseElement); // container would miss the portalled dialog
  ```

- **Mocked timers break axe-core.** `axe` uses `setTimeout` internally and will hang, then
  fail with a test timeout, if timers are faked. Restore real timers around the scan:

  ```ts
  vi.useRealTimers();
  const results = await axe(container);
  vi.useFakeTimers();
  ```

- **Clean up between renders.** `@testing-library/react` auto-cleans when `globals: true`
  (this repo's `frontend/vitest.config.ts` sets it), so each scan sees only its own render.
  Without cleanup, a scan of `document.body` or `baseElement` picks up leftovers from earlier
  tests and reports violations against the wrong component.
- **CSS is not loaded.** `frontend/vitest.config.ts` sets `css: false`, so Tailwind classes
  contribute nothing to the DOM under test. Anything that depends on applied styles belongs
  to the page layer.

## 4. TypeScript wiring under Vitest 4

`jest-axe` ships no types; `@types/jest-axe` declares the module but registers the matcher
against Jest's global namespace, not Vitest's. Add a one-file augmentation. Vitest 4 exports
the `Matchers` interface from the `vitest` module, and `Assertion` extends it, so this is the
single place to declare it:

```ts
// frontend/src/__tests__/axe-matchers.d.ts
import "vitest";

declare module "vitest" {
  interface Matchers<T = any> {
    toHaveNoViolations(): T;
  }
}
```

On Vitest 1.x the equivalent is augmenting `Assertion` and `AsymmetricMatchersContaining`
instead — the pattern `@testing-library/jest-dom` uses. This repo is on Vitest 4; use
`Matchers`.

Register the matcher once in the existing setup file rather than in every test:

```ts
// frontend/src/__tests__/setup.ts  (existing file — append, do not replace)
import "@testing-library/jest-dom/vitest";
import { expect } from "vitest";
import { toHaveNoViolations } from "jest-axe";

expect.extend(toHaveNoViolations);
```

> Editing `setup.ts` is a change to a human-authored file. Propose the two added lines as a
> diff and let the developer apply them; do not silently rewrite the file.

## 5. Verifying the wiring before trusting a clean result

A misconfigured scan reports zero violations and looks like success. Prove the harness fails
before you accept a pass — the same discipline the QA Agent applies to every generated test:

```ts
it("the axe harness actually reports violations", async () => {
  const { container } = render(<div><img src="/logo.png" /></div>); // no alt text
  const results = await axe(container, AXE_RUN_OPTIONS);
  expect(results.violations.map(v => v.id)).toContain("image-alt");
});
```

If that assertion does not fail against a fixed component and pass against the broken one,
the wiring is wrong and every other result from it is meaningless.

Sanity checks for a page scan:

- `results.passes.length > 0` — a scan that passed nothing scanned nothing.
- `results.url` matches the route you meant to scan.
- `results.testEngine.version` is the axe-core version you expect.

## 6. Where the files go in this repo

| Artifact | Path | Runner |
|---|---|---|
| Shared tag set (component) | `frontend/src/__tests__/axe-helpers.ts` | imported, not collected |
| Component a11y tests | `frontend/src/__tests__/<component>-a11y.test.tsx` | `cd frontend && npm run test` |
| Matcher registration | `frontend/src/__tests__/setup.ts` | Vitest `setupFiles` |
| Matcher types | `frontend/src/__tests__/axe-matchers.d.ts` | `tsc -b` |
| Shared tag set (page) | `e2e/axe-helpers.ts` | imported, not collected |
| Page a11y specs | `e2e/<route>-a11y.spec.ts` | `cd e2e && npx playwright test` |

Vitest collects `**/*.{test,spec}.?(c|m)[jt]s?(x)`, so `axe-helpers.ts` is imported but never
run as a suite. Playwright's `testDir` here is `e2e/` itself, and its `webServer` block
starts both the .NET API and the Vite dev server, so page scans need no manual server
startup.
