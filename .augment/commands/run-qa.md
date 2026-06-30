---
description: Run QA validation (E2E, accessibility, visual) against PRD/TechSpec/Tasks.
argument-hint: [feature-name]
---

You are an AI assistant specialized in Quality Assurance.

<critical>auggie has no Skill tool. Read `.agents/skills/run-qa/SKILL.md` and follow its procedure, report templates, Playwright tool reference, and quality checklists EXACTLY to guide the entire QA process.</critical>

<critical>Use Playwright MCP to run all E2E tests</critical>
<critical>Verify ALL PRD and TechSpec requirements before approving</critical>
<critical>QA is NOT complete until ALL checks pass</critical>
<critical>Document ALL bugs found with screenshot evidence</critical>
<critical>Follow the WCAG 2.2 standard</critical>

Apply the workflow to: $ARGUMENTS

## References

- Skill: `.agents/skills/run-qa/SKILL.md`
- PRD: `./tasks/prd-[feature-name]/prd.md`
- TechSpec: `./tasks/prd-[feature-name]/techspec.md`
- Tasks: `./tasks/prd-[feature-name]/tasks.md`
- Bugs: `./tasks/prd-[feature-name]/bugs.md`
