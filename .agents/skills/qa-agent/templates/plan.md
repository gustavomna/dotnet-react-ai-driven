<!--
HOW TO FILL THIS TEMPLATE

1. Delete this comment block entirely. Line 1 of the finished file must be either the
   inference notice (when no requirement artifact was found) or the `# QA Plan` heading.
2. Replace every <PLACEHOLDER>. Delete rows and sections that do not apply; never leave a
   placeholder behind — an unresolved <PLACEHOLDER> is a plan that was not finished.
3. Every row in the criteria table needs a layer AND a reason. One criterion, one layer.
4. Every criterion that cannot be automated goes in the Manual items table with a real
   reason, and reaches `summary.json` as a `manualItems[]` entry.
5. Keep this file row-for-row identical to `plan.json` in the same directory.
6. Walk `checklists/plan-review.md` before generating a single test.

Generate the skeleton with:
  python3 .agents/skills/qa-agent/scripts/qa.py plan --round <N> --scope <scope.json> --stack <stack.json>
-->

> **This plan is inference-based.** No requirement artifact was found for this scope, so
> the expected behaviour below was derived from the diff and the public interfaces it
> touches. It states what the code appears to be for, not what it was specified to do.
> Delete this block when `inferenceBased` is `false`.

# QA Plan — Round <NNN>

- Scope sources: <diff | paths | ref-range | requirements | packages>
- Base / ref range: <main...HEAD>
- Packages: <frontend, backend>
- Requirement documents: <tasks/prd-<feature>/prd.md, tasks/prd-<feature>/techspec.md> (or `none — inference-based`)
- Detected stack: <vitest (unit) | dotnet + xunit (unit, integration) | playwright (e2e) | vitest-axe + @axe-core/playwright (a11y)>
- Layers available this round: <unit, integration, e2e, a11y>
- Layers unavailable: <a11y — axe tooling not installed (jest-axe, @axe-core/playwright)> (or `none`)

## Criteria

| Check | Requirement | Layer | Target | Reason | Status |
|---|---|---|---|---|---|
| CHK-001 | <FR-1> — <criterion text, quoted from the requirement document> | <unit> | <backend/src/Backend.Api/Program.cs> | <pure request/response contract; provable through the real HTTP pipeline without a browser> | <planned> |
| CHK-002 | <FR-5> — <criterion text> | <unit> | <frontend/src/App.tsx> | <component render only; no browser or network needed> | <generated> |
| CHK-003 | <UX-1> — <criterion text> | <a11y> | <frontend/src/App.tsx> | <accessible name and role are only observable on a rendered tree> | <planned> |
| CHK-004 | <UX-2> — <criterion text> | <e2e> | <http://localhost:5173/> | <needs a real viewport to prove the layout at 320 px> | <planned> |
| CHK-005 | <FR-2> — <criterion text> | <integration> | <backend/tests/Backend.Api.Tests/HealthEndpointTests.cs> | <already covered by a human-authored test; extended, not duplicated> | <existing> |

`Status` is one of `planned`, `generated`, `manual`, `existing`.

## Test files

| Check | Test file | New or extended | Collision |
|---|---|---|---|
| <CHK-002> | <frontend/src/__tests__/health-indicator.test.tsx> | <new> | <none> |
| <CHK-003> | <frontend/src/__tests__/health-indicator.a11y.test.tsx> | <new> | <none> |
| <CHK-005> | <backend/tests/Backend.Api.Tests/HealthEndpointTests.cs> | <existing, untouched> | <human-authored — sibling file written instead: <path>> |

Collisions are recorded here and in the round summary. A human-authored test is never
overwritten; a sibling file is written and the collision reported.

## Manual items

| Requirement | Why it cannot be automated |
|---|---|
| <UX-3> — <criterion text> | <requires visual judgement of layout density; no assertable threshold exists> |
| <FR-9> — <criterion text> | <depends on a third-party sandbox account with no test credentials available in CI> |

These surface as open items in every summary. They are never counted as passes.

## Not covered

| In-scope file | Why no check | 
|---|---|
| <frontend/src/index.css> | <token-only change; no behaviour and no rendered difference asserted by any criterion> |

An in-scope source file with no check and no stated reason is a coverage gap, not an
omission. List it or cover it.

## Coverage

| | Count |
|---|---|
| Criteria | <12> |
| Automated | <10> |
| Manual | <2> |
| Uncovered | <0> |

## Notes

- <Any ambiguity that was resolved by judgement rather than by the requirement text, and how.>
- <Any layer that will be skipped this round, and the reason a reader will see in the summary.>
