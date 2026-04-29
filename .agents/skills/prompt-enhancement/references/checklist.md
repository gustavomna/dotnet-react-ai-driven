# Structured Prompt Validation Checklist

Use this checklist to validate the generated prompt before delivering it to the user.

## Blocks

- [ ] `<task>` present and concise (one line)
- [ ] `<goals>` present (one focusing sentence)
- [ ] `<role>` defines the agent and the context
- [ ] `<requirements>` separated into Business, Technical, UI/UX
- [ ] `<critical>` includes required skills and out of scope
- [ ] `<workflow>` included when the task is complex (multiple steps)
- [ ] `<output>` included when the output format is relevant
- [ ] `<endpoints>` included when there are APIs or backend
- [ ] `<tests>` included when there are endpoints or flows to validate

## Quality

- [ ] Explicit requirements (nothing implicit or vague)
- [ ] Out of scope uses *DO NOT* or *NEVER* for emphasis
- [ ] Endpoints with method, route, and status codes
- [ ] UI/UX includes loading, errors, and visual feedback when applicable
- [ ] Delimiter `---` between long blocks (5+ lines)
