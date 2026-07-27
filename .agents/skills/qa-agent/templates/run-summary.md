<!--
HOW TO FILL THIS TEMPLATE

1. Delete this comment block. Save as `qa/rounds/<NNN>/summary.md`.
2. Writing this file SEALS the round. Sealed rounds are never edited or deleted; the next
   QA run allocates the next round number.
3. Lead with the verdict word and the per-severity counts. Then the first few issues.
   Then the path to the rest. Never paste raw runner output here — it lives in the layer
   logs under `runs/<runId>/`.
4. The verdict is the WORD `PASS` or `FAIL`. Never colour, icon, or symbol alone.
   When any layer was skipped, the line reads `PASS — INCOMPLETE (<layer>: <reason>)`,
   never a bare `PASS`.
5. This file must agree with `summary.json` on verdict, completeness, and every count.
   Regenerate both from the same run; never hand-edit a verdict.
6. Walk `checklists/pre-verdict.md` before publishing.
-->
# QA Round <NNN> — Summary

**Verdict: <FAIL>**

<Use exactly one of:
  Verdict: PASS
  Verdict: PASS — INCOMPLETE (a11y: skipped-unavailable — axe tooling not installed)
  Verdict: FAIL
A bare PASS is only permitted when every layer executed.>

| Severity | Count |
|---|---|
| critical | <1> |
| high | <1> |
| medium | <0> |
| low | <0> |
| **total** | **<2>** |

- Round directory: `qa/rounds/<NNN>`
- Run directory: `qa/rounds/<NNN>/runs/<20260725-140233>`
- Generated at: <2026-07-25T14:06:02Z>
- Author: <qa-agent>

## Findings

| Issue | Severity | Source | Location | Title |
|---|---|---|---|---|
| `issue_001` | <high> | <unit> | <frontend/src/App.tsx:47> | <one-line title> |
| `issue_002` | <critical> | <a11y> | <frontend/src/App.tsx:52> | <one-line title> |
| `issue_003` | <medium> | <flake> | <e2e/app.spec.ts:12> | <one-line title> |

<Show the first three to five findings, most severe first. Then:>

Remaining <N> findings: `qa/rounds/<NNN>/issue_004.md` through `qa/rounds/<NNN>/issue_<NNN>.md`.

## Layers

| Layer | Status | Exit | Reproduce |
|---|---|---|---|
| unit | <failed> | <1> | `<cd frontend && npm run test -- --run>` |
| integration | <passed> | <0> | `<dotnet test backend/tests/Backend.Api.Tests/Backend.Api.Tests.csproj>` |
| e2e | <passed> | <0> | `<cd e2e && npx playwright test>` |
| a11y | <skipped-unavailable> | <n/a> | <axe tooling not installed (jest-axe, @axe-core/playwright)> |

Status is one of `passed`, `failed`, `flaky`, `skipped-unavailable`. A flaky layer is never
reported as passed.

## Skipped layers

| Layer | Reason |
|---|---|
| <a11y> | <axe tooling not installed (jest-axe, @axe-core/playwright)> |

<When this table is non-empty, `complete` is `false` and the verdict line carries the
INCOMPLETE qualifier. With `gate.skippedLayers: "fail"` (the CI default) a skip is
promoted to a FAIL. Delete the section when no layer was skipped.>

## Manual items

| Criterion | Reason |
|---|---|
| <UX-3 minimal page layout> | <requires visual judgement> |

These are open items. They were never automated and are not part of the pass.

## Baseline and suppressions

| | |
|---|---|
| Baseline used | <yes — qa/baseline.json> |
| Pre-existing findings (informational, non-blocking) | <3> |
| Introduced findings (gating) | <2> |
| Suppressions valid / invalid / expired | <1 / 0 / 0> |

<List every invalid or expired suppression by id, and confirm its check ran anyway.>

## Coverage

| | Count |
|---|---|
| Criteria | <12> |
| Automated | <10> |
| Manual | <2> |
| Uncovered | <0> |

## Accessibility scope statement

<Include this section whenever the a11y layer ran.>

Automated accessibility scanning catches roughly a third to a half of real accessibility
issues. This round reports what axe and the keyboard checks could prove against WCAG 2.2
Level AA. It is not a compliance statement, and a clean a11y layer does not mean the
interface is accessible.

## Next

- <Fix the findings, then re-run: a new round is allocated automatically.>
- <Raw per-layer output: `qa/rounds/<NNN>/runs/<runId>/<layer>.log`.>
- <Machine-readable gate: `qa/rounds/<NNN>/summary.json`.>
