# Stack Detection

The agent adapts to the project's test stack. It never imposes one.

```bash
python3 .agents/skills/qa-agent/scripts/qa.py detect --repo .
```

Exit code 3 (`NO_STACK`) with `"detected": false` when **no** layer is available.

## The hard rule

**The agent never installs a test framework, a test runner, an assertion library, an axe
package, or a browser binary.**

Choosing a test framework commits a project to a toolchain, a CI shape, and a maintenance
burden for years. That is a human decision. When nothing is detectable the agent stops and
reports: what it probed, what was absent, and a recommendation a human can accept or reject.
It does not run `npm install`, `dotnet add package`, `npx playwright install`, or any other
command that mutates dependencies — not even as a "one-time setup convenience".

The same rule applies per layer. A repository with Vitest but no axe packages gets a working
`unit` layer and an `a11y` layer reported unavailable — not an auto-installed `jest-axe`.

## What is probed

### JavaScript / TypeScript

| Layer | Probe | Result |
|---|---|---|
| unit | `package.json` with a `test` script; runner inferred from devDependencies | `vitest` → vitest, `jest` → jest |
| integration | a `test:integration` script, or a test directory named `integration` / `__integration__` | targeted command for that directory |
| e2e | `playwright.config.*` → `npx playwright test`; `cypress.config.*` → cypress | e2e target with its config path |
| a11y | `jest-axe` or `vitest-axe` in devDependencies (component), `@axe-core/playwright` (page) | available only when the package is present |

The package manager comes from the lockfile (`package-lock.json` → npm, and likewise for the
others). **This repository is npm-only** — every command in this bundle's examples uses npm.
Generic multi-manager detection exists for other repositories; it is not licence to introduce
yarn, pnpm, or bun here.

### .NET

| Layer | Probe | Result |
|---|---|---|
| unit | `*.sln` or `*.csproj`; a test project is a csproj referencing `Microsoft.NET.Test.Sdk`, `xunit`, `nunit`, or `MSTest` | `dotnet test <path>` |
| integration | a test project also referencing `Microsoft.AspNetCore.Mvc.Testing` (`WebApplicationFactory`) | `dotnet test <path>` filtered to the integration project |

### Runtimes

- `node` — `node --version`.
- `dotnet` — `dotnet --version`.
- `headlessBrowser` — **both** `npx playwright --version` succeeding **and** a browsers cache
  present (`~/Library/Caches/ms-playwright` or `~/.cache/ms-playwright`). A Playwright package
  without downloaded browsers is not a usable headless browser.

## What "available" means per layer

A layer is `available: true` only when **all** of the following hold:

1. A runner is installed and resolvable from the project (in `devDependencies` / restored
   packages, not merely mentioned in documentation).
2. A concrete, runnable command exists — argv, cwd, and a report flag where the runner offers a
   machine-readable reporter.
3. At least one target file or directory matches the layer's globs, or the layer can
   legitimately run empty (an e2e config with no specs is `available` but produces no checks).
4. The runtime the layer needs is present — Node for JS layers, the .NET SDK for .NET layers, a
   headless browser for `e2e` and page-level `a11y`.

Anything less is `available: false` with a `reason` that **names the missing thing**:

- `"axe tooling not installed (jest-axe, @axe-core/playwright)"`
- `"no integration test target detected"`
- `"playwright browsers not downloaded (run: npx playwright install)"`

`"no integration test target detected"` is **not an error**. Many projects have no integration
layer. It is a skip with a reason, and it is reported as such.

## The skipped-unavailable contract

An unavailable layer is never silently omitted and never counted as a pass.

1. `exec` records it with `status: "skipped-unavailable"`, `exitCode: null`, and the detection
   `reason` carried through verbatim.
2. `summary.json` lists it in `skippedLayers[]`.
3. `complete` becomes `false`.
4. The human verdict line reads `PASS — INCOMPLETE (a11y: skipped-unavailable)`, never a bare
   `PASS`.
5. `gate.skippedLayers` in `qa/qa.config.json` is `"warn"` by default; set it to `"fail"` to
   promote a skip to a failing verdict. CI examples set `"fail"`.

The reason must be actionable: a human reading `skippedLayers[]` should know exactly what to
install or configure. What the agent may **not** do is install it, silently drop the layer, or
substitute a weaker check and present it as the missing one — a component-level axe scan does
not cover a page route, and saying it does is a false pass.

## Conventions the agent must conform to

`conventions` in the detect output is binding on generation:

```json
{
  "testFileSuffixes": [".test.ts", ".test.tsx", ".spec.ts", "Tests.cs"],
  "fileNaming": "kebab-case",
  "assertionLibraries": ["vitest", "fluentassertions"],
  "e2eFramework": "playwright",
  "componentTestLibrary": "@testing-library/react"
}
```

Generated tests use the reported suffix, naming style, directory, assertion library, and
fixture pattern. Do not introduce a second convention — a repository with one testing style and
a foreign-looking generated file has been made worse, not safer.

## Re-detection between rounds

The detected stack, the baseline, and granted suppressions persist between rounds so they are
not re-derived. Re-run `detect` when a lockfile, a `*.csproj`, or a runner config changed in
scope; otherwise reuse the previous round's `stack.json` and record that you did.
