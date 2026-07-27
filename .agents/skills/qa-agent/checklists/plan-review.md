# Checklist — Plan Review

Walk this list **before generating or running a single test**. The subject is
`qa/rounds/NNN/plan.md` and `qa/rounds/NNN/plan.json`, produced by:

```bash
python3 .agents/skills/qa-agent/scripts/qa.py plan --round <N> --scope <scope.json> --stack <stack.json>
```

Every item is phrased so that **yes = proceed**. A single `no` blocks generation: fix the
plan and walk the list again from the top. Never turn a `no` into a `yes` by deleting the
criterion, widening the target, or downgrading a check to `manual` without a real reason.

---

## 1. Criteria coverage

- [ ] **Does every stated acceptance criterion from the requirement documents appear in the criteria table exactly once?**
      *If no:* re-read each file in `requirementDocs[]` and add the missing rows. A criterion silently absent from the plan becomes a silent pass later.
- [ ] **Is each criterion quoted or paraphrased with a source reference (`file#Lnn`) so a reader can find it?**
      *If no:* add `source` to the `requirements[]` entry. Un-sourced criteria cannot be audited.
- [ ] **Is every criterion in the table traceable to one `CHK-NNN` id?**
      *If no:* allocate the id. The id is what the generated test header and the issue file both cite.

## 2. Layer assignment

- [ ] **Does every check name exactly one layer — `unit`, `integration`, `e2e`, or `a11y`?**
      *If no:* pick one. A criterion split across two layers means the criterion is really two criteria; split the row instead.
- [ ] **Does every check state a `reason` for its layer that a reviewer could disagree with?**
      *If no:* replace filler ("appropriate layer", "best fit") with the real driver — "pure logic, no DOM needed", "needs the real HTTP pipeline via `WebApplicationFactory`", "needs a browser to observe focus order".
- [ ] **Is the cheapest layer that can actually prove the criterion the one chosen?**
      *If no:* demote. An E2E test for a pure reducer is slow, flaky, and proves less than a unit test.
- [ ] **Is every layer used by the plan reported `available: true` in the stack document?**
      *If no:* either remove the check or mark it `manual` with the unavailability as its `manualReason`. Planning against a layer that cannot run produces a fake pass.

## 3. Targets

- [ ] **Does every check name a concrete target — a file path or a route — that exists on disk or is reachable at `http://localhost:5173`?**
      *If no:* resolve it. "The health component", "the settings area", and `TBD` are not targets.
- [ ] **Is every `testFile` path inside a detected test directory and named per the detected convention?**
      *If no:* move it. Frontend tests live under `frontend/src/__tests__/` with kebab-case names ending `.test.ts`/`.test.tsx`; Playwright specs live under `e2e/` ending `.spec.ts`; .NET tests live under `backend/tests/<Project>.Tests/` ending `Tests.cs`.
- [ ] **Does every UI file in scope (`touchesUi: true`) have at least one `a11y` check pointed at it or at a route that renders it?**
      *If no:* add it. The PRD makes accessibility automatic on any UI change — it is never opt-in.

## 4. Manual items

- [ ] **Is every criterion that cannot be automated marked `status: manual` with a non-empty `manualReason`?**
      *If no:* fill the reason. "Requires visual judgement", "needs a physical screen-reader pass", "depends on a third-party sandbox account with no test credentials" are reasons; "hard" is not.
- [ ] **Is `manual` used only where automation is genuinely impossible, not merely inconvenient?**
      *If no:* automate it. Viewport width, focus order, and error copy are all automatable.
- [ ] **Will every manual item reach `summary.json` as a `manualItems[]` entry?**
      *If no:* fix the plan so it does. A manual item that never surfaces is indistinguishable from a pass.

## 5. Honesty about derivation

- [ ] **When no requirement artifact was found, is `inferenceBased` set to `true` and does the first line of `plan.md` say the plan is inference-based?**
      *If no:* set it and say it. An inferred plan asserts what the code appears to do, not what it was supposed to do, and the reader must know which one they are holding.
- [ ] **When `inferenceBased` is `true`, does every requirement row cite the diff hunk or public interface it was inferred from?**
      *If no:* add the citation. Inference without a source is guessing.
- [ ] **Are inferred criteria kept out of the `stated criterion` severity path?**
      *If no:* correct them. Only an explicit stated criterion forces `high`; an inferred failure defaults to `medium`.

## 6. Duplication and collisions

- [ ] **Does every planned check extend or complement existing coverage rather than restate it?**
      *If no:* drop the duplicate and point the check at the existing test with `status: existing`. Two tests asserting the same thing double the runtime and halve the signal.
- [ ] **Is every planned `testFile` that collides with a human-authored file resolved as a sibling file, with the collision recorded in `plan.md`?**
      *If no:* rename to a sibling and record it. Overwriting a human-authored test is forbidden with no exception.
- [ ] **Does the plan leave existing passing tests untouched?**
      *If no:* revert the edits. The plan adds coverage; it never renegotiates coverage that already exists.

## 7. Scope integrity

- [ ] **Is every in-scope source file either covered by a check or listed with a stated reason for having none?**
      *If no:* add the check or the reason. Silent gaps are the failure mode this plan exists to prevent.
- [ ] **Are all target files inside the repository's test directories, `qa/`, or new sibling test files?**
      *If no:* remove them. The agent's write scope is exactly those three.
- [ ] **Does `coverage` in the plan add up — `criteria == automated + manual + uncovered`?**
      *If no:* recount before proceeding.

---

## Proceed gate

All boxes ticked, in this order:

1. `plan.json` and `plan.md` agree row for row.
2. `plan.md` first line is the inference notice, or the round heading when the plan is requirement-backed.
3. Collisions and manual items are visible in `plan.md`, not only in `plan.json`.

Then, and only then, move on to test generation and `checklists/generated-test.md`.
