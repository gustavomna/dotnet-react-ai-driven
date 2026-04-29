# AI-Driven Development Starter

A project template designed for building full-stack applications with AI agents (Claude Code / Claude CLI). It includes a complete workflow — from PRD creation to implementation, code review, QA, and bug fixing — all orchestrated through Claude commands, agents, and skills.

## Stack

- **Frontend**: React 19 + Vite 8 + TypeScript + Tailwind CSS v4 + shadcn/ui (base-nova)
- **Backend**: .NET 10 + ASP.NET Core Web API
- **Frontend Testing**: Vitest (unit) + Playwright (E2E)
- **Backend Testing**: xUnit + FluentAssertions
- **Frontend Package Manager**: npm

## Quick Start

```bash
# 1. Clone the template
git clone <this-repo-url> my-project
cd my-project

# 2. Install everything (frontend + e2e npm deps + .NET restore)
./scripts/bootstrap.sh

# 3. Start development in two terminals
# Terminal 1 — Backend
cd backend && dotnet watch run

# Terminal 2 — Frontend
cd frontend && npm run dev
```

Frontend runs on `localhost:5173`, backend on `localhost:5080`. The scaffold ships with a `/api/health` endpoint and a frontend indicator that reads it through the Vite proxy — open `http://localhost:5173` and you should see `Backend health: ok`. (Port 5080 instead of the usual 5000 because macOS reserves :5000 for the AirPlay Receiver.)

### What runs on clone

The template is not empty. It comes with:

- A minimal React 19 + Vite 8 + Tailwind v4 frontend wired to shadcn (`base-nova`).
- A minimal .NET 10 Web API exposing `GET /api/health`.
- A Playwright smoke test that exercises both.
- A worked example PRD at [`tasks/prd-example-health-check/`](./tasks/prd-example-health-check/) showing the shape of PRD / Tech Spec / Tasks the AI workflow produces.

This walking skeleton exists so the AI has a real project to extend — and so you can confirm the stack is healthy before running `/create-prd`.

## How to Use This as a Base for New Projects

### Step 1: Clone and clean

```bash
git clone <this-repo-url> my-new-project
cd my-new-project
rm -rf tasks/prd-example-health-check  # drop the worked example once you've read it
rm docs/prompt.md                      # you'll write your own in Step 3
git init
```

### Step 2: Customize CLAUDE.md

Edit `CLAUDE.md` to reflect your project's specific needs. This file is what AI agents read first — it's their ground truth. Update ports, project names, and skill references as needed.

### Step 3: Write Your Feature Prompt

Create a new file in `docs/prompt.md` describing what you want to build. It should contain business requirements, technical constraints, UI/UX specs, and endpoint definitions.

### Step 4: Run the AI Workflow

The workflow follows a structured pipeline. Each step has a dedicated Claude command:

```
PRD → Tech Spec → Tasks → Implementation → Review → QA → Bugfix
```

**Using Claude Code CLI commands:**

```bash
# 1. Create the PRD from your prompt
claude "/create-prd"

# 2. Generate the Tech Spec from the PRD
claude "/create-techspec"

# 3. Break the spec into implementable tasks
claude "/create-tasks"

# 4. Implement each task
claude "/run-task"

# 5. Review the code
claude "/run-review"

# 6. Run QA
claude "/run-qa"

# 7. Fix any bugs found
claude "/run-bugfix"
```

**Or automate everything with the runner script:**

```bash
# Dry-run: list discovered tasks + completion state, exit without running Claude
./run-tasks.sh tasks/prd-my-feature --list

# Run all pending tasks sequentially
./run-tasks.sh tasks/prd-my-feature

# Targeted runs
./run-tasks.sh tasks/prd-my-feature --only 3
./run-tasks.sh tasks/prd-my-feature --from 2 --no-skip-completed
./run-tasks.sh tasks/prd-my-feature --max-turns 80
./run-tasks.sh tasks/prd-my-feature --dangerously-skip-permissions
```

## Project Structure

```
├── .claude/
│   ├── commands/          # Claude CLI slash commands (the AI workflow)
│   │   ├── create-prd.md          # /create-prd — Create PRD
│   │   ├── create-techspec.md     # /create-techspec — Create Tech Spec
│   │   ├── create-tasks.md        # /create-tasks — Create task breakdown
│   │   ├── run-task.md            # /run-task — Implement a task
│   │   ├── run-review.md          # /run-review — Code review
│   │   ├── run-qa.md              # /run-qa — Quality assurance
│   │   └── run-bugfix.md          # /run-bugfix — Fix bugs
│   ├── agents/            # Council agents (task-reviewer, architect-advisor, ...)
│   └── skills/            # Symlinks into .agents/skills + local skill(s)
├── .agents/
│   └── skills/            # External AI skills (cria-prd, executar-task, dotnet-best-practices, ...)
├── templates/             # Document templates used by commands
│   ├── prd-template.md
│   ├── techspec-template.md
│   ├── tasks-template.md
│   └── task-template.md
├── tasks/
│   └── prd-example-health-check/  # Worked example — delete once you're comfortable
├── docs/
│   └── prompt.md          # Your feature description / requirements
├── frontend/              # React 19 + Vite 8 app (scaffolded, runs on clone)
├── backend/               # .NET 10 ASP.NET Core Web API (scaffolded, runs on clone)
├── e2e/                   # Playwright E2E tests
├── scripts/
│   ├── bootstrap.sh       # One-shot: preflight + npm install + dotnet restore
│   └── _preflight.sh      # Shared preflight helpers
├── playwright.config.ts   # Playwright config (boots both servers via webServer)
├── run-tasks.sh           # Batch runner for all tasks via Claude CLI (supports --list, --only, --from)
├── .mcp.json              # Context7 + Playwright MCP servers used by the commands
├── .editorconfig          # Editor/AI formatting contract (2-space JS/TS, 4-space C#)
├── CLAUDE.md              # AI agent instructions (read this first)
├── AGENTS.md              # Pointer to CLAUDE.md
└── skills-lock.json       # External skills registry
```

## AI Workflow Details

### Commands

Each command in `.claude/commands/` is a Claude Code slash command. When you run `/create-prd` in Claude Code, it reads the corresponding markdown file and follows the instructions, activating the appropriate skill.

### Skills

Skills are reusable instruction sets that teach the AI how to perform specific tasks well. They live in `.agents/skills/` (external) and `.claude/skills/` (local). The commands reference skills by name — the AI loads them at runtime.

### Agents

The `task-reviewer` agent is automatically triggered after task implementation to validate code quality and generate review artifacts.

### Templates

Templates in `templates/` define the structure of generated documents (PRDs, tech specs, tasks). The AI fills them in based on your requirements.

### Runner Script

`run-tasks.sh` automates sequential task execution. It discovers `N_task.md` files in a PRD folder, checks completion status in `tasks.md`, and runs Claude CLI for each pending task.

## Available Commands

| Command | Description |
|---|---|
| `npm run dev` | Start frontend dev server |
| `npm run build` | Build frontend |
| `npm run typecheck` | Type check frontend |
| `npm run lint` | Lint frontend |
| `npm run test` | Run frontend unit tests |
| `dotnet run` | Start backend API server |
| `dotnet build` | Build backend |
| `dotnet test` | Run backend xUnit tests |
| `dotnet watch run` | Backend with hot-reload |
| `npx playwright test` | Run E2E tests |

## Customization Tips

- **Add a database**: Add Entity Framework Core or Dapper to the backend, create a new skill for it, and reference it in `CLAUDE.md`
- **Change the UI library**: Replace shadcn with another library, update `components.json` and the skill references
- **Add new commands**: Create a new `.md` file in `.claude/commands/` following the existing pattern
- **Add new skills**: Place them in `.agents/skills/` or `.claude/skills/` and reference them in your commands
