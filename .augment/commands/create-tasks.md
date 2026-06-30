---
description: Break a PRD and Tech Spec into a sequenced, testable task list.
argument-hint: [feature-name or PRD path]
---

You are an assistant specialized in software development project management. Your task is to create a detailed task list based on a PRD and a Tech Spec.

<critical>auggie has no Skill tool. Read `.agents/skills/create-tasks/SKILL.md` and follow its procedure, templates, and quality checklists EXACTLY to guide the entire task creation process.</critical>

<critical>**BEFORE GENERATING ANY FILES, SHOW ME THE HIGH-LEVEL TASK LIST FOR APPROVAL**</critical>
<critical>DO NOT IMPLEMENT ANYTHING</critical>
<critical>EACH TASK MUST BE A FUNCTIONAL AND INCREMENTAL DELIVERABLE</critical>
<critical>IT IS ESSENTIAL THAT FOR EACH TASK THERE IS A SET OF TESTS THAT ENSURES ITS FUNCTIONALITY AND BUSINESS OBJECTIVE</critical>

Apply the workflow to: $ARGUMENTS

## References

- Skill: `.agents/skills/create-tasks/SKILL.md`
- Templates: `.agents/skills/create-tasks/assets/`
- Required PRD: `tasks/prd-[feature-name]/prd.md`
- Required Tech Spec: `tasks/prd-[feature-name]/techspec.md`
- Output: `./tasks/prd-[feature-name]/tasks.md` and `./tasks/prd-[feature-name]/[num]_task.md`
