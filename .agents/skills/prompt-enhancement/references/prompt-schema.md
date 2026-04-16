# Prompt Schema (Structured Format)

Structured prompts use XML blocks to organize context. Each block has a specific purpose. Prompt engineering techniques applied: contextual priming, delimiters, XML tags, output format control.

## Required Blocks

| Block | Purpose | Example |
|-------|---------|---------|
| `<task>` | Concise one-line description of the task | `<task>Weather Dashboard Implementation</task>` |
| `<role>` | Agent role and task context | `<role>You are a senior full-stack developer...</role>` |
| `<requirements>` | Requirements organized by category | Business, Technical, UI/UX |
| `<critical>` | Constraints and required skills | Skills, out of scope |

## Optional Blocks (include when applicable)

| Block | Purpose | When to use |
|-------|---------|-------------|
| `<goals>` | Objective in one sentence (focus) | Whenever it helps direct the model's attention |
| `<workflow>` | Reasoning steps (Chain-of-Thought) | Complex tasks with multiple steps |
| `<output>` | Expected output format | JSON, table, markdown, file structure |
| `<profile>` | Author, version, language | Reusable or versioned prompts |
| `<endpoints>` | APIs, routes, payloads | When there is API or backend integration |
| `<tests>` | Validations and tests | When there are endpoints or flows to validate |

## Delimiters

Between long blocks (more than 5 lines), use `---` as a visual separator. Explicit delimiters improve model precision and stability.

## `<requirements>` Structure

```
### Business
- Business requirements (what the user needs)

### Technical
- Technical requirements (stack, architecture, data flow)

### UI/UX
- Interface and experience requirements
```

## `<critical>` Structure

```
### Required skills
- List of project skills that should be activated

### Out of Scope
- What MUST NOT be implemented (explicit)
```

## `<goals>` Structure

A sentence summarizing the main objective. Example: "Implement weather dashboard consuming Open-Meteo via the backend, with responsive UI and visual feedback."

## `<workflow>` Structure

Numbered steps for complex tasks (Chain-of-Thought). Example:

```
1. [First logical step]
2. [Second step]
3. [Third step]
```

## `<output>` Structure

Specify format: "React code + .NET endpoint", "JSON with fields X, Y, Z", "Markdown table", etc.

## `<profile>` Structure

```
- author: [name]
- version: [semver]
- language: [pt-BR, en, etc.]
```
