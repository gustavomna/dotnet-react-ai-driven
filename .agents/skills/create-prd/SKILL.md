---
name: create-prd
description: Creates Product Requirements Documents (PRDs) from feature requests following a structured workflow of clarification, planning, and drafting. Outputs a standardized PRD to the project tasks directory. Use when the user asks to create a PRD, define requirements, or document a new feature. Do not use for technical specifications, task breakdowns, or implementation planning.
---

# PRD Creation

## Procedures

**Step 1: Validate Prerequisites**
1. Confirm the feature name or description has been provided by the user.
2. Derive the slug in kebab-case for the output directory: `./tasks/prd-[feature-slug]/`.

**Step 2: Clarify Requirements (Mandatory)**
1. Ask the user clarification questions using the AskUserQuestion tool before generating any content.
2. Cover all areas from the clarification checklist:
   - **Problem and Objectives**: What problem to solve, measurable goals.
   - **Users and Stories**: Primary users, user stories, main flows.
   - **Core Functionality**: Data inputs/outputs, actions.
   - **Scope and Planning**: What is NOT included, dependencies.
   - **Design and Experience**: UI/UX guidelines and accessibility.
3. Do NOT proceed to Step 3 until clarification answers are received.

**Step 3: Plan the PRD (Mandatory)**
1. Create a development plan including:
   - Section-by-section approach.
   - Areas requiring research (use Web Search for business rules).
   - Assumptions and dependencies.
2. Present the plan to the user for alignment.

**Step 4: Draft the PRD (Mandatory)**
1. Read the template at `assets/prd-template.md`.
2. Focus on WHAT and WHY, never on HOW (implementation belongs in Tech Spec).
3. Include numbered functional requirements.
4. Keep the document under 2,000 words.
5. Do NOT deviate from the template structure.

**Optional Step (before Step 5): Council Consultation**

Skip for trivial features or unambiguous requirements. Invoke when the PRD is non-trivial, the value hypothesis feels weak, or the user asks for "council review".

1. Dispatch in parallel (single assistant message, two `Agent` tool calls):
   - `product-mind` — challenge the value hypothesis: who specifically benefits, what's the measurable outcome, what's the opportunity cost vs. other roadmap items
   - `devils-advocate` — surface unstated assumptions, edge cases the requirements ignore, ways this PRD could pass acceptance and still miss its actual goal
2. Pass each agent a prompt of the form:
   ```
   PRD draft for "<feature>": <paste the drafted PRD or its functional requirements>.
   Return 3–5 bullets in your archetype voice. End with one **Key Point:** line.
   ```
3. Incorporate the feedback by either (a) revising the PRD draft, (b) appending an "Open Questions" section listing concerns not yet resolved, or (c) noting in the Step 6 report what was raised and consciously deferred. Do not silently ignore the feedback.

**Step 5: Save the PRD (Mandatory)**
1. Create the directory: `./tasks/prd-[feature-slug]/`.
2. Save the PRD to: `./tasks/prd-[feature-slug]/prd.md`.

**Step 6: Report Results**
1. Provide the final file path.
2. Provide a brief summary of the PRD outcome.

## Core Principles
- Clarify before planning; plan before drafting.
- Minimize ambiguity; prefer measurable statements.
- PRD defines outcomes and constraints, NOT implementation.
- Always consider usability and accessibility.

## Quality Checklist
- [ ] Clarification questions completed and answered.
- [ ] Detailed plan created.
- [ ] PRD generated using the template.
- [ ] Numbered functional requirements included.
- [ ] File saved to `./tasks/prd-[feature-slug]/prd.md`.
- [ ] Final path provided.

## Error Handling
- If the user provides insufficient context, ask follow-up clarification questions before proceeding.
- If the template file is missing, report the error and halt — do not generate a PRD without the template.
- If the output directory already exists, confirm with the user before overwriting.
