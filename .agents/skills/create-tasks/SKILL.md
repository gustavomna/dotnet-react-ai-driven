---
name: create-tasks
description: Converts PRD and Tech Spec into a detailed, sequenced list of implementation tasks. Each task is a functional, incremental deliverable with its own test suite. Outputs tasks.md and individual task files. Use when the user asks to create tasks, break down work, or plan implementation from an existing PRD and Tech Spec. Do not use for PRD creation, tech spec creation, or actual code implementation.
---

# Task Creation

## Procedures

**Step 1: Validate Prerequisites**
1. Confirm the feature slug has been provided.
2. Verify the PRD exists at `tasks/prd-[feature-slug]/prd.md`. If missing, halt.
3. Verify the Tech Spec exists at `tasks/prd-[feature-slug]/techspec.md`. If missing, halt.

**Step 2: Analyze PRD and Tech Spec (Mandatory)**
1. Read the PRD completely to extract requirements.
2. Read the Tech Spec completely to extract technical decisions.
3. Identify main components and their dependencies.

**Step 3: Generate High-Level Task List (Mandatory)**
1. Present the high-level task list to the user for approval BEFORE generating any files.
2. Organize tasks by logical deliverable.
3. Order tasks logically: dependencies before dependents (e.g., backend before frontend, both before E2E tests).
4. Each task MUST be a functional, incremental deliverable.
5. Each task MUST have its own set of unit and integration tests.
6. Limit to a maximum of 15 tasks (group as needed).
7. Wait for user approval before proceeding to Step 4.

**Optional Step (before presenting in Step 3): Council Consultation**

Skip for features with fewer than 5 tasks or trivial sequencing. Invoke when the breakdown spans frontend + backend + infra, has cross-task dependencies, or the PRD has tight deadlines.

1. Dispatch in parallel (single assistant message, two `Agent` tool calls):
   - `pragmatic-engineer` — task sizing realism, sequencing for incremental delivery, "could a junior actually finish this in a day", which tasks should be split or merged
   - `devils-advocate` — hidden dependencies between tasks, order-of-operations issues, tasks that look independent but aren't, things the breakdown silently assumes are already done
2. Pass each agent a prompt of the form:
   ```
   Task breakdown for "<feature>": <paste the high-level list with each task title + 1-line description>.
   Tech Spec summary: <one-paragraph>.
   Return 3–5 bullets in your archetype voice. End with one **Key Point:** line.
   ```
3. Revise the high-level list based on feedback BEFORE presenting it to the user in Step 3. The user should see the council-improved list, not the raw first draft.

**Step 4: Generate Task Files (Mandatory)**
1. Read the tasks summary template at `assets/tasks-template.md`.
2. Read the individual task template at `assets/task-template.md`.
3. Create the summary file: `./tasks/prd-[feature-slug]/tasks.md`.
4. Create individual task files: `./tasks/prd-[feature-slug]/[num]_task.md`.
5. Use format X.0 for main tasks, X.Y for subtasks.
6. Do NOT repeat implementation details already in the Tech Spec — reference it instead.

**Step 5: Report Results**
1. Present all generated files to the user.
2. Await confirmation before any implementation begins.

## Guidelines
- Assume the primary reader is a junior developer — be as clear as possible.
- Group tasks by logical deliverable.
- Make each main task independently completable.
- Define clear scope and deliverables for each task.
- Include tests as subtasks within each main task.
- Do NOT implement anything — focus solely on task listing and detailing.

## Quality Checklist
- [ ] PRD and Tech Spec analyzed.
- [ ] High-level task list approved by user.
- [ ] Task files generated using templates.
- [ ] Each task has unit and integration test subtasks.
- [ ] Files saved to `./tasks/prd-[feature-slug]/`.
- [ ] Results presented to user.

## Error Handling
- If the PRD or Tech Spec is missing, halt and direct the user to the `create-prd` or `create-techspec` skill.
- If the user rejects the high-level task list, revise based on feedback and re-present for approval.
- If the output directory already contains task files, confirm with the user before overwriting.
