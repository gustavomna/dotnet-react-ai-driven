---
description: Perform a code review of the current changes against project rules.
argument-hint: [feature-name or scope]
---

You are an AI assistant specialized in Code Review.

<critical>auggie has no Skill tool. Read `.agents/skills/run-review/SKILL.md` and follow its procedure, report templates, code quality checklists, and approval criteria EXACTLY to guide the entire code review process.</critical>

<critical>Use git diff to analyze code changes</critical>
<critical>Verify the code complies with the project rules</critical>
<critical>ALL tests must pass before approving the review</critical>
<critical>The implementation must follow the TechSpec and Tasks EXACTLY</critical>

Apply the workflow to: $ARGUMENTS

## References

- Skill: `.agents/skills/run-review/SKILL.md`
- PRD: `./tasks/prd-[feature-name]/prd.md`
- TechSpec: `./tasks/prd-[feature-name]/techspec.md`
- Tasks: `./tasks/prd-[feature-name]/tasks.md`
