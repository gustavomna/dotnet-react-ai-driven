---
description: Fix all documented bugs from bugs.md with regression tests.
argument-hint: [feature-name]
---

You are an AI assistant specialized in bug fixing.

<critical>auggie has no Skill tool. Read `.agents/skills/run-bugfix/SKILL.md` and follow its procedure, report templates, and quality checklists EXACTLY to guide the entire bug fixing process.</critical>

<critical>You MUST fix ALL bugs listed in the bugs.md file</critical>
<critical>For EACH bug fixed, create regression tests that simulate the original problem and validate the fix</critical>
<critical>DO NOT apply superficial fixes or hacks — resolve the root cause of each bug</critical>
<critical>The task is NOT complete until ALL bugs are fixed and ALL tests are passing with 100% success</critical>
<critical>START IMPLEMENTATION IMMEDIATELY after planning — do not wait for approval</critical>
<critical>Use Context7 MCP to analyze the documentation for the language, frameworks, and libraries involved in the fix</critical>

Apply the workflow to: $ARGUMENTS

## References

- Skill: `.agents/skills/run-bugfix/SKILL.md`
- Bugs: `./tasks/prd-[feature-name]/bugs.md`
- PRD: `./tasks/prd-[feature-name]/prd.md`
- TechSpec: `./tasks/prd-[feature-name]/techspec.md`
