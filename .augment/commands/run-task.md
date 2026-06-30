---
description: Implement a feature task with tests, then run the task review.
argument-hint: [task-number]
---

You are an AI assistant responsible for correctly implementing tasks.

<critical>auggie has no Skill tool. Read `.agents/skills/run-task/SKILL.md` and follow its procedure EXACTLY for setup, analysis, planning, implementation, and review.</critical>

<critical>Identify and load the skills necessary to execute the task based on the technologies used (read the relevant `.agents/skills/<skill>/SKILL.md` files)</critical>
<critical>**YOU MUST** start the implementation right after planning.</critical>
<critical>Use Context7 MCP to analyze the documentation for the language, frameworks, and libraries involved in the implementation</critical>
<critical>After completing the task, mark it as complete in tasks.md</critical>
<critical>ALWAYS use the `task-reviewer` agent at the end</critical>

Implement task: $ARGUMENTS

## References

- Skill: `.agents/skills/run-task/SKILL.md`
- Reviewer agent: `.augment/agents/task-reviewer.md`
- PRD: `./tasks/prd-[feature-name]/prd.md`
- Tech Spec: `./tasks/prd-[feature-name]/techspec.md`
- Tasks: `./tasks/prd-[feature-name]/tasks.md`
