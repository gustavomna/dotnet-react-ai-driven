---
name: council
description: Orchestrates a multi-agent debate among 6 advisor archetypes (architect-advisor, devils-advocate, pragmatic-engineer, product-mind, security-advocate, the-thinker) to stress-test a decision. Runs 4 phases — framing, parallel opening statements, parallel rebuttals, synthesis. Use when the user asks for a "council", "debate", "advisors weigh in", or when a non-trivial architectural, product, or security decision needs multi-perspective scrutiny. Do not use for simple implementation questions, code review, or single-domain tasks where one agent suffices.
---

# Council Debate

## Procedures

**Step 1: Frame the Question (Mandatory)**
1. Restate the decision under debate in one sentence. If the user prompt is ambiguous, ask 1–2 clarification questions with `AskUserQuestion` before dispatching agents — never invent context.
2. Detect flags in the user's invocation:
   - `--quick` — skip the rebuttal phase (openings + synthesis only).
   - `--save` — write the final transcript to `./tasks/council/<slug>-<YYYY-MM-DD>.md`.
3. Pick the 4–6 archetypes most relevant to the question. The full roster is `architect-advisor`, `devils-advocate`, `pragmatic-engineer`, `product-mind`, `security-advocate`, `the-thinker`. For purely product/UX debates, `security-advocate` may be omitted; for pure infra/security debates, `product-mind` may be omitted. Default: dispatch all 6.

**Step 2: Opening Statements — Parallel Dispatch (Mandatory)**
1. In a **single assistant message**, send one `Agent` tool call per archetype (parallel). Each call uses `subagent_type: <archetype-name>` and a prompt of the form:
   ```
   Council debate. Question: "<the framed question>"

   Deliver your Opening Statement following your archetype's format:
   - 2–3 paragraphs in character
   - End with a one-line **Key Point:** summarizing your stance

   Do not address other archetypes yet — this is the opening round.
   ```
2. Wait for all 6 (or 4–5) results to return before proceeding.

**Step 3: Rebuttals — Parallel Dispatch (Skip if `--quick`)**
1. Compile the openings into a brief "Opponents' Positions" block listing each archetype's **Key Point** verbatim (the one-liners only — don't bundle the full openings, that bloats the sub-agent prompts).
2. In a single assistant message, send one `Agent` tool call per archetype (parallel) with a prompt of the form:
   ```
   Council debate. Question: "<the framed question>"

   Your own Key Point was: "<this archetype's Key Point from Step 2>"

   Opponents' Key Points:
   - architect-advisor: <...>
   - devils-advocate: <...>
   - pragmatic-engineer: <...>
   - product-mind: <...>
   - security-advocate: <...>
   - the-thinker: <...>

   Deliver your Rebuttal (1–2 paragraphs):
   - Concede explicitly where opponents' Key Points show your concern is misapplied or premature
   - Push back where they would introduce a violation of your archetype's core priorities
   - End with a one-line **Final Position:** that may differ from your opening Key Point if you've conceded ground
   ```

**Step 4: Synthesis (Mandatory, Orchestrator Only)**
The main orchestrator — NOT a sub-agent — writes the synthesis. Do not dispatch a 7th agent for this; synthesis is the orchestrator's job because it must weigh evidence across all positions.

The synthesis must contain:
1. **Convergence** — where 4+ archetypes agreed.
2. **Live disagreements** — where positions remained split, with the strongest argument on each side.
3. **Recommendation** — a concrete decision (or two named options if the council genuinely deadlocked), grounded in the strongest arguments, not a vote count.
4. **Risks accepted** — what concerns are being knowingly deferred and why.

**Step 5: Output Format (Mandatory)**
Emit a single markdown transcript with these sections, in order:
```markdown
# Council Debate — <one-line question>

## Question
<the framed question, 1–2 sentences of context>

## Opening Statements
### Architect Advisor
<full opening>
**Key Point:** <...>

### Devil's Advocate
<full opening>
**Key Point:** <...>

[... one section per dispatched archetype ...]

## Rebuttals
[omit this section entirely if --quick]
### Architect Advisor
<rebuttal>
**Final Position:** <...>

[... one per archetype ...]

## Synthesis
### Convergence
- ...

### Live Disagreements
- **<topic>:** <position A> vs. <position B>

### Recommendation
<concrete decision>

### Risks Accepted
- ...
```

**Step 6: Save (Only if `--save`)**
1. Derive a slug from the question (kebab-case, max 6 words).
2. Create the directory `./tasks/council/` if missing.
3. Write the full transcript to `./tasks/council/<slug>-<YYYY-MM-DD>.md`.
4. Report the file path back to the user.

## Core Principles
- Parallel dispatch always. Sending agents serially defeats the point of multi-perspective debate and wastes turns.
- Archetypes stay in character. If a sub-agent returns generic content, re-dispatch once with the prompt clarified — do not let archetypes converge into the same voice.
- Synthesis is judgment, not voting. A 5-vs-1 split where the 1 is correct still favors the 1. Cite the strongest argument, not the headcount.
- No new archetypes invented mid-debate. Use only the 6 defined in `.claude/agents/`.

## Quality Checklist
- [ ] Question framed in one sentence before any agent dispatch.
- [ ] All openings dispatched in parallel (one assistant message, multiple Agent calls).
- [ ] Each archetype's opening ends with **Key Point:**.
- [ ] Rebuttals dispatched in parallel (unless `--quick`).
- [ ] Each rebuttal ends with **Final Position:** (unless `--quick`).
- [ ] Synthesis written by the orchestrator, not a sub-agent.
- [ ] Synthesis names a concrete recommendation, not a vote tally.
- [ ] Transcript saved to `./tasks/council/<slug>-<date>.md` if `--save` passed.

## Error Handling
- If a sub-agent times out or returns an error: re-dispatch that single archetype once. If it fails twice, note its absence in the transcript and continue — do not block the whole council on one failure.
- If the user invokes `/council` without a question, ask for one via `AskUserQuestion`. Do not synthesize council debates about empty prompts.
- If `--save` is set but the file path already exists, append `-2`, `-3`, etc. — never overwrite a prior transcript.
