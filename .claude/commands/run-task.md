You are an AI assistant responsible for correctly implementing tasks.

<critical>Activate and follow the `run-task` skill to guide the entire implementation process. The skill contains the complete procedure for setup, analysis, planning, implementation, and review.</critical>

<critical>Identify and load the skills necessary to execute the task based on the technologies used</critical>
<critical>**YOU MUST** start the implementation right after planning.</critical>
<critical>Use Context7 MCP to analyze the documentation for the language, frameworks, and libraries involved in the implementation</critical>
<critical>After completing the task, mark it as complete in tasks.md</critical>
<critical>ALWAYS RUN @task-reviewer at the end</critical>

## References

- Skill: `run-task`
- PRD: `./tasks/prd-[feature-name]/prd.md`
- Tech Spec: `./tasks/prd-[feature-name]/techspec.md`
- Tasks: `./tasks/prd-[feature-name]/tasks.md`
