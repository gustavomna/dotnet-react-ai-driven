# PRD: QA Agent

## Overview

AI coding agents write code and then assert that it works. The assertion is the weakest link: implementation and self-validation come from the same reasoning pass, so a mistaken agent validates its own mistake. Code review catches design and intent problems, but review reads code — it does not execute it. Nothing in a typical agent-assisted workflow owns *verification*.

The QA Agent closes that gap. It is a standalone, tool-agnostic agent definition plus a companion skill bundle that reads whatever requirement artifacts a project has (specs, tickets, acceptance criteria, or just a diff), derives a test plan from them, generates and executes automated tests across unit, integration, end-to-end, and accessibility layers, and emits every failure as a structured issue file that a human or a remediation agent can act on.

It is for developers who currently accept "the agent said it works" as proof, and for teams that need an enforceable quality gate before a pull request opens. Its value is that verification stops being a claim and becomes an artifact: a test suite committed to the repository, a run log with exit codes, and a findings file per failure.

The accessibility capability is modeled on the `a11y-testing` skill (axe-core, jest-axe, `@axe-core/playwright`, WCAG 2.2 AA). Its packaging — a `SKILL.md` entry point plus `references/`, `checklists/`, `templates/`, and `examples/` directories — is the shape every QA capability in this agent follows.

## Goals

- A developer can invoke one command against a branch, a diff, or a spec and get a test suite written to the repository, executed, and a pass/fail verdict grounded in stated acceptance criteria.
- Every failing check becomes a self-contained issue file with a reproducing command, so remediation is mechanical rather than investigative.
- Accessibility violations (WCAG 2.2 Level A and AA) are detected automatically on any change touching UI, without the developer asking for them.
- Tests are traceable: each generated test names the requirement or criterion it covers, so coverage gaps are visible instead of implied.
- A completion claim can no longer rest on assertion alone — the evidence is a run log with per-layer exit status.
- Suppressing a check — disabling a lint or axe rule, skipping a test, excluding a selector — becomes impossible to do silently; it requires a recorded, reviewable justification with an expiry condition.
- The agent runs identically in three contexts: interactively inside a coding agent, headless in CI, and as a one-off audit on a repository with no prior setup.
- The agent adapts to the project's existing test stack rather than imposing one.

## User Stories

- **US-001–US-012** — Scope resolution and test plan derivation from requirements, diffs, and existing tests.
- **US-013–US-024** — Test generation and execution across unit, integration, and E2E layers.
- **US-025–US-034** — Accessibility auditing and WCAG 2.2 AA gating.
- **US-035–US-044** — Findings reporting, severity assignment, and handoff to remediation.
- **US-045–US-052** — CI invocation, configuration, and suppression governance.

[Full user stories](_user_stories.md)

## Core Features

### 1. Scope Resolution and Test Plan Derivation

Determines what changed and what it was supposed to do, then maps each acceptance criterion to a concrete check at a named layer.

Functional requirements:
- Accept scope from any of: an explicit path or package, a git ref range, a requirements document, or the working tree diff. When several are given, the intersection wins; when none is given, the diff against the default branch is the scope.
- Read any requirement artifacts the project provides — specs, tickets, acceptance criteria, story catalogs — and treat them as the source of expected behavior. When none exist, derive expected behavior from the diff and public interfaces, and state that the plan is inference-based.
- Emit a plan file listing, per criterion: the requirement reference, the chosen layer (unit, integration, E2E, a11y), the target file or route, and the reason for that layer.
- Detect the project's existing test stack — runner, assertion library, E2E framework, fixtures, directory conventions — and conform to it.
- Mark criteria that cannot be automated as `manual` with a stated reason. They surface as an open item, never as a silent pass.

### 2. Test Generation

Writes test files into the repository's existing test layout, following discovered conventions.

Functional requirements:
- Each generated test carries a header naming the requirement and criterion it covers.
- Interactive components get their non-happy states covered — error, loading, disabled, empty — not only the success path.
- Never overwrite a human-authored test. Extend it or add a sibling file, and report the collision.
- Generated tests must be deterministic: no wall-clock dependence, no unseeded randomness, no calls to live third-party services.
- Generated tests must fail for the right reason. Every new test is verified to fail against the pre-change state or a deliberately broken assertion before it is accepted as coverage.

### 3. Test Execution

Runs the suite and captures machine-readable results.

Functional requirements:
- Execute unit, integration, E2E, and a11y layers in that order. A failing layer does not stop the remaining layers, so one round reports every problem.
- Persist raw output per run under a timestamped directory with per-layer exit codes and a summary.
- Detect flakiness by re-running only failed tests once. A test that passes on retry is reported as `flaky`, never as `passed`.
- Record the exact command used for each layer so a human can reproduce the run by hand.
- Stream per-layer progress during execution so a long suite is not mistaken for a hang.

### 4. Accessibility Auditing

The a11y layer, adopted from the `a11y-testing` skill.

Functional requirements:
- Component-level scanning with `jest-axe` over rendered components including their interactive states.
- Page-level scanning with `@axe-core/playwright` over primary routes and post-interaction states — modal open, form submitted, error shown.
- Tags fixed at `wcag2a`, `wcag2aa`, `wcag22aa`.
- Violations map to severity by axe impact: `critical` and `serious` become `critical` and `high`, `moderate` becomes `medium`, `minor` becomes `low`.
- Rule disabling and broad `exclude()` selectors are rejected. Only third-party widget subtrees may be excluded, and only with a recorded justification.
- Keyboard-reachability and focus-order checks run alongside the axe scan, since automated rule engines do not cover them.

### 5. Findings Reporting

Converts every failure into a self-contained, machine-parseable issue file.

Functional requirements:
- Write one `issue_NNN.md` per failure into a numbered findings round, with YAML frontmatter carrying `status`, `file`, `line`, `severity`, `author`, and `source`.
- One issue per failure. Never combine unrelated problems into one file.
- The body states the failing assertion, observed versus expected behavior, the reproducing command, and a concrete suggested fix.
- A clean round writes no issue files and records a pass verdict in the run summary.
- Emit a machine-readable summary (JSON) alongside the markdown so CI and other tools can gate on it without parsing prose.

### Feature Interaction

Derivation feeds generation, generation feeds execution, execution feeds reporting. The issue files are the agent's only output contract: any remediation loop — human, agent, or CI bot — consumes them without needing to understand the QA agent's internals. Fixes re-enter the agent on the next round, closing the loop. Detected stack, baseline, and granted suppressions persist between rounds so they are not re-derived.

## Business Rules

- Scope resolution yields exactly one target set per round. The agent never writes outside the repository's test directories and its own output directory.
- A findings round is numbered and immutable once written. Re-running QA creates the next round; existing rounds are never edited or deleted.
- Issue numbering within a round is zero-padded to three digits and continues from the highest existing issue in that round.
- Severity is exactly one of `critical`, `high`, `medium`, `low`. A failing test of an explicit stated acceptance criterion is at minimum `high`. An accessibility failure inherits the axe impact mapping. A flaky test is at minimum `medium` and is never dismissed by a passing retry.
- Verdict rule: a round is `pass` only when every executed layer exits zero and no test is marked flaky. Any other state is `fail`.
- The agent may never make a check pass by weakening it. Deleting a test, skipping a test, disabling a rule, widening a tolerance, or broadening an exclusion is forbidden as a response to failure. The only permitted response to a failure is an issue file.
- A suppression is valid only when recorded with three parts: the exact target, the reason, and an expiry condition (a date, a version, or a linked ticket). A suppression missing any part is invalid and the check runs.
- Baseline rule: on a repository with pre-existing violations, the round gates on violations introduced by the current scope. Pre-existing violations are recorded as informational `low` issues and never block. The baseline is a committed file, regenerated only by explicit request.
- Generated tests belong to the repository, not to the round. They are committed with the change and outlive it.
- The agent has read access to the whole repository and write access limited to test files, its own output directory, and the current findings round.
- When no test stack is detectable, the agent stops and reports. Adding a test framework to a project is a human decision.
- When a required runtime is unavailable — no headless browser, no display server — the affected layer reports `skipped-unavailable`. A skipped layer never counts toward a pass.

## User Experience

**Personas.** The *feature developer* wants the code they just shipped to be verified before review. The *repository maintainer* wants QA enforced in CI without hand-writing gates per feature. The *auditor* has a repository they did not write and wants a quality and accessibility snapshot on demand.

**Primary flow — interactive.** The developer invokes the agent after finishing a change. It reports the detected stack and the derived plan, asks for confirmation only where the plan is genuinely ambiguous, then generates, runs, and reports. It ends with a verdict line, the run directory path, and a per-severity count of findings.

**Secondary flow — CI.** A pipeline step runs the agent headless against a pull request branch and fails the job on a `fail` verdict, publishing the run summary and findings as artifacts and posting the per-severity counts back to the pull request.

**Secondary flow — one-off audit.** Pointed at a repository with no prior configuration, the agent detects the stack, runs read-only checks and accessibility scans, and reports findings without generating or committing tests unless asked.

**UI/UX considerations.** All output is markdown and plain terminal text. Failure output leads with counts by severity, then the first few issues, then the path to the rest — never a wall of raw runner output. The first run in a repository explains what it detected and what it will write before it writes anything.

**Accessibility of the agent's own output.** Verdicts never rely on color alone; `PASS` and `FAIL` are written words. Progress output remains meaningful when read linearly by a screen reader.

**Onboarding and discoverability.** Installation is a single command that places the agent definition and skill bundle where the host runtime discovers them. Configuration is optional; every setting has a working default derived from the detected stack.

## High-Level Technical Constraints

- The agent must be portable across coding-agent runtimes. It declares its capabilities and prompt in a plain-text definition and depends on no single vendor's API or model.
- Findings and run artifacts are plain markdown and JSON under version control, readable without the tool that wrote them.
- Test execution runs locally against the project's own toolchain. No repository content or test code is transmitted to a third-party quality service.
- Accessibility conformance target is WCAG 2.2 Level AA.
- Browser-based layers require a headless browser; its absence degrades to a reported skip, never a silent pass.
- A round on a mid-sized change should complete within a standard CI job timeout without special tuning.
- The agent must operate on repositories it has never seen, with no project-specific configuration required for a first run.
- Secrets and environment values needed for integration or E2E layers are read from the environment, never written into generated tests, findings, or logs.

## Non-Goals (Out of Scope)

- **Replacing code review.** Review reads intent and design; QA runs checks. The two remain separate activities with separate outputs.
- **Manual and exploratory testing.** The agent automates what can be automated and marks the rest `manual`. It does not simulate a human tester.
- **Performance, load, and security testing.** Distinct disciplines with distinct tooling, outside this effort's boundary.
- **Visual regression testing.** Requires baseline image management and infrastructure this version does not take on.
- **Installing or choosing a test framework for a project that has none.** The agent reports and stops.
- **Merging, pushing, or releasing after a passing round.** The agent reports a verdict; acting on it stays a human decision.
- **Guaranteeing accessibility compliance.** Automated scanning catches roughly a third to a half of real issues. The agent reports what it can prove and says so explicitly.
- **Mutation testing and coverage-percentage targets.** Coverage is asserted against stated criteria, not against a line-percentage threshold.

## Architecture Decision Records

- [ADR-001: Ship as an agent definition plus a skill bundle, not a monolithic tool](adrs/adr-001.md) — Keeps QA composable with existing workflows, portable across runtimes, and usable standalone, instead of coupling it to one pipeline.
- [ADR-002: The issue file is the only output contract](adrs/adr-002.md) — Findings are self-contained markdown with parseable frontmatter, so any remediation consumer works without knowing the agent's internals.
- [ADR-003: Adopt the `a11y-testing` stack and packaging](adrs/adr-003.md) — axe-core, jest-axe, `@axe-core/playwright`, WCAG 2.2 AA tags, and the `SKILL.md` plus references/checklists/templates/examples layout become the template for every QA capability.
- [ADR-004: Gate on newly introduced violations against a committed baseline](adrs/adr-004.md) — Makes the agent adoptable on existing repositories with accumulated debt without either blocking every run or hiding regressions.
- [ADR-005: Suppression requires a recorded justification with an expiry condition](adrs/adr-005.md) — Prevents the common failure mode where a quality gate is quietly weakened until it reports nothing.
- [ADR-006: Generated tests are verified to fail before they count as coverage](adrs/adr-006.md) — A test that passes unconditionally is worse than no test, because it reports safety that does not exist.

## Open Questions

- Should findings rounds share a numbering sequence with the project's code-review rounds where one exists, or maintain an independent sequence? Sharing simplifies remediation; separating keeps QA history readable on its own.
- Where does configuration live when the project has no convention — a dedicated config file, the existing package manifest, or agent-definition frontmatter only?
- Should a missing or stale QA round hard-block a completion claim, or warn? Hard-blocking is stronger but breaks changes that legitimately have nothing to test, such as documentation.
- For monorepos, does the agent derive scope per changed package automatically, or require an explicit package target?
- Should the agent commit generated tests itself, or leave every write staged for the developer to commit?
- How is the baseline invalidated when a major dependency upgrade legitimately changes the violation set?
