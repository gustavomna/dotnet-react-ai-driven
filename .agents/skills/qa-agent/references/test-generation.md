# Test Generation

Generated tests belong to the repository, not to the round. They are committed with the change
and outlive it. Write them the way the project already writes tests — the detected
`conventions` (see [stack-detection.md](stack-detection.md)) are binding.

Generation is skipped entirely in one-off audit mode.

## The per-test requirement header

Every generated test file opens with a header naming what it covers, so a coverage gap is
visible instead of implied.

```ts
/**
 * Requirement: FR-3 — tasks/prd-x/prd.md#L42
 * Criterion:   The list shows an empty state when there are no results.
 * Layer:       unit — pure render behavior, no network boundary crossed.
 * Generated:   qa-agent, round 001. Fail-first verified (inverted assertion).
 */
```

```csharp
// Requirement: FR-7 — tasks/prd-x/prd.md#L88
// Criterion:   POST /api/items returns 400 when the name is empty.
// Layer:       integration — exercises model validation through the HTTP pipeline.
// Generated:   qa-agent, round 001. Fail-first verified (base revision).
```

On an inference-based plan there is no requirement reference. Cite what the expectation was
inferred from instead — the exported signature, the controller route, the diff hunk — and say
`Requirement: inferred`.

Per-test assertions that map to a criterion name it in the test title, so a failure in the
runner output is already traceable before anyone opens an issue file:
`it('FR-3: renders the empty state when items is empty', ...)`.

## Non-happy-path coverage

A happy-path-only test suite is the failure mode this agent exists to prevent. **Every
interactive component gets its non-happy states covered**, each as its own case:

| State | What to assert |
|---|---|
| **error** | The error message renders, the retry affordance exists, no stale success content remains |
| **loading** | The pending indicator renders, actions that would double-submit are disabled |
| **disabled** | The control cannot be activated by click **or** by keyboard, and communicates its state to assistive technology |
| **empty** | The empty message renders — not a spinner, not a bare container |

Extend the same discipline outward: boundary values, an unexpected `null`, a rejected promise,
a non-2xx response, a cancelled request. For .NET, the equivalent is invalid input, a missing
record, a conflicting write, and an unauthorized caller.

Each non-happy state that maps to a stated criterion gets its own `checks[]` row. States with
no stated criterion are still worth covering; they are recorded as inferred and their failures
default to severity `medium`.

## Never overwrite a human-authored test

A human-authored test encodes intent the agent does not have. Overwriting one destroys
information and can silently delete coverage.

1. **Extend** — add cases to the existing file when the conventions and fixtures match and the
   file is the natural home for the criterion.
2. **Add a sibling** — when extension would distort the file, create a new file next to it whose
   name makes the relationship obvious (`foo.test.tsx` → `foo.empty-state.test.tsx`).
3. **Report the collision** either way — the file, the criterion, and which route was taken —
   in `plan.md` and in the round summary, so a human can reconcile the two.

Never rewrite, reformat, reorder, or "clean up" an existing test file while extending it. Never
delete a case you did not write. A generated test that conflicts with a human assertion is a
finding, not a merge conflict to resolve in the agent's favour.

## Determinism requirements

A non-deterministic test is worse than no test: it trains the team to ignore red.

- **No wall-clock dependence.** Never `new Date()`, `Date.now()`, `DateTime.Now`, or "today" in
  an assertion. Inject a clock or freeze time with the runner's fake timers.
- **No unseeded randomness.** Fixed fixtures, or a seeded generator with the seed written into
  the test.
- **No live third-party calls.** No network to anything the test does not own. Use the
  project's existing mocking or stubbing convention; for .NET integration tests, use
  `WebApplicationFactory` with a test double, not a live dependency.
- **No cross-test order dependence.** Each test sets up and tears down its own state. Never rely
  on a previous test having run.
- **No sleeps as synchronization.** Wait on the condition (`findBy*`, `expect.poll`,
  Playwright's auto-waiting), never on a duration.
- **No environment leakage.** A test must pass on a clean machine, in CI, and at 23:59 UTC on
  the last day of a month.

## Secrets

Secrets and environment values needed by integration or E2E layers are **read from the
environment**. They are **never** written into generated tests, findings, logs, plans, or
summaries.

- Reference the variable name, never the value: `process.env.API_TOKEN`,
  `Environment.GetEnvironmentVariable("API_TOKEN")`.
- A missing required variable makes the layer report a skip with the variable **name** in the
  reason — never a dump of the environment.
- Execution redacts anything matching a token/secret/password/key/credential pattern to
  `***REDACTED***` in logs, `run.json`, and issue files. Do not defeat that by pasting a value
  into an issue body "for reproduction". The reproduce command names the variable and lets the
  human supply it.

## Fail-first verification (ADR-006)

**A test counts as coverage only after it has been observed failing for the right reason.** A
test that passes unconditionally reports safety that does not exist.

### Method A — run against the pre-change state (preferred)

Use a throwaway worktree. Never `git stash`, `git restore`, `git reset`, or `git checkout` the
developer's working tree — those are destructive and require explicit permission.

```bash
git worktree add /tmp/qa-fail-first "$(git merge-base HEAD main)"
cp frontend/src/__tests__/foo.test.tsx /tmp/qa-fail-first/frontend/src/__tests__/
cd /tmp/qa-fail-first/frontend && npm run test -- --run src/__tests__/foo.test.tsx
# expect: FAIL — "Unable to find an element with the text: No results"
cd - && git worktree remove /tmp/qa-fail-first
```

Method A is only meaningful when the pre-change state actually lacks the behavior. For a test
covering code that existed before the change, use Method B.

### Method B — deliberately broken assertion

```bash
# 1. Invert exactly one assertion in the new test:
#    expect(screen.getByText('No results')).toBeInTheDocument()
# -> expect(screen.queryByText('No results')).not.toBeInTheDocument()
cd frontend && npm run test -- --run src/__tests__/foo.test.tsx -t "FR-3: renders the empty state"
# expect: FAIL, and the message must name the empty-state element

# 2. Restore the original assertion.
# 3. Re-run and confirm PASS. A test left inverted is a silent false pass.
```

### Verifying the failure is the right failure

An observed failure proves nothing until its message matches the criterion. These do **not**
count and mean the test itself is broken — fix it and repeat:

- `Cannot find module` / `error CS0246` — the test never reached the assertion.
- `Unable to find an element` caused by a wrong selector rather than absent behavior.
- A fixture, factory, or `WebApplicationFactory` that failed to construct.
- A timeout with no assertion evaluated.

### Recording and reporting

- Note the method used in the test header (`Fail-first verified (inverted assertion)`).
- Mark the check `generated` in `plan.json` only after verification passes.
- A test that **cannot** be made to fail is not coverage. Remove it from the coverage count or
  replace it, and say so in the round summary — never keep it and count it.
- Never leave an inverted assertion, a `.only`, or a debugging `console.log` behind. Re-run the
  layer once more before Step 6 to confirm the working tree is clean of verification scaffolding.

## Before the round runs

Check every generated file against [../checklists/generated-test.md](../checklists/generated-test.md).
Generated tests are left **unstaged** in the working tree — `generation.autoStage` defaults to
`false` and the agent never commits.
