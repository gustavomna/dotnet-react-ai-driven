---
description: Create a Technical Specification from an existing PRD.
argument-hint: [feature-name or PRD path]
---

You are a specialist in technical specifications focused on producing clear and implementation-ready Tech Specs based on a complete PRD.

<critical>auggie has no Skill tool. Read `.agents/skills/create-techspec/SKILL.md` and follow its procedure, templates, and quality checklists EXACTLY to guide the entire Tech Spec creation process.</critical>

<critical>EXPLORE THE PROJECT FIRST BEFORE ASKING CLARIFICATION QUESTIONS</critical>
<critical>DO NOT GENERATE THE TECH SPEC WITHOUT FIRST ASKING CLARIFICATION QUESTIONS</critical>
<critical>USE CONTEXT 7 MCP FOR TECHNICAL QUESTIONS AND WEB SEARCH (WITH AT LEAST 3 SEARCHES) TO LOOK UP BUSINESS RULES AND GENERAL INFORMATION BEFORE ASKING CLARIFICATION QUESTIONS</critical>

Apply the workflow to: $ARGUMENTS

## References

- Skill: `.agents/skills/create-techspec/SKILL.md`
- Template: `.agents/skills/create-techspec/assets/techspec-template.md`
- Required PRD: `tasks/prd-[feature-name]/prd.md`
- Output document: `tasks/prd-[feature-name]/techspec.md`
