---
name: prompt-enhancement
description: Transforms vague or poorly structured prompts into structured prompts using XML and Markdown. Applies techniques: goals, workflow (Chain-of-Thought), output format, few-shot patterns, delimiters. Produces prompts with task, goals, role, requirements (business, technical, UI/UX), workflow, output, endpoints, tests, and critical constraints. Do not use for prompts that are already well-structured or for general documentation.
---

# Prompt Enhancement

Transforms vague or poorly structured prompts into structured prompts using XML and Markdown, following best practices and bringing more context to the executing agent.

## Procedure

**Step 1: Analyze the input prompt**

1. Read the prompt provided by the user in full.
2. Identify the main task, implicit and explicit requirements, mentioned APIs, and constraints.
3. Read `references/prompt-schema.md` to understand the output structure.
4. Read `references/before-after-example.md` to see the transformation pattern.
5. If the task is complex or ambiguous, read `references/few-shot-examples.md` for examples by type.

**Step 2: Extract and categorize**

1. Extract the task into a single concise line for `<task>`.
2. Define `<goals>`: a sentence summarizing the main objective (model focus).
3. Define the `<role>` based on context (stack, domain, task type). Include the reference to the task.
4. Separate requirements into:
   - **Business:** what the user needs in terms of value/functionality.
   - **Technical:** stack, architecture, data flow (frontend ↔ backend ↔ external API).
   - **UI/UX:** responsiveness, loading, errors, visual feedback, accessibility.
5. If the task has multiple steps, extract `<workflow>` with numbered steps (Chain-of-Thought).
6. If the output format is relevant, define `<output>` (code, JSON, table, structure).
7. If there are APIs or endpoints, document them in `<endpoints>` with URL, method, status codes, and payload.
8. If there are endpoints, add `<tests>` with validations (e.g., curl to test).
9. In `<critical>`, list:
   - **Required skills:** relevant project skills (frontend-design, shadcn, ui-ux-pro-max, etc.).
   - **Out of Scope:** what *MUST NOT* be implemented, using *DO NOT* or *NEVER* for emphasis.

**Step 3: Assemble the structured prompt**

1. Read `assets/structured-prompt-template.md` for the skeleton.
2. Fill each block with the extracted and categorized content.
3. Remove empty or non-applicable blocks (e.g., `<endpoints>` if there are no APIs; `<workflow>` for simple tasks).
4. Between long blocks (more than 5 lines), insert `---` as a visual delimiter.
5. Ensure vague requirements are made explicit (e.g., "show the data" → "cards with icons, interactive chart, skeleton loading").

**Step 4: Validate**

1. Read `references/checklist.md` and verify each item.
2. Run `python3 scripts/validate-structure.py` passing the generated prompt via stdin to confirm required blocks.
3. Confirm there are no interpretation gaps (the executing agent should not have to guess).

## Error Handling

- **Already structured prompt:** If the input prompt already contains XML blocks (`<task>`, `<role>`, etc.), inform the user and offer refinement instead of full restructuring.
- **Insufficient context:** If the prompt is too vague (e.g., "build an app"), ask the user for more details (stack, features, APIs) before generating the structured prompt.
- **Unknown skills:** If the project does not have explicit skills, use generic domain skills (frontend-design, shadcn, ui-ux-pro-max for UI; vercel-react-best-practices for React).
- **Validation failed:** If `scripts/validate-structure.py` returns an error, add the missing blocks to the generated prompt.
