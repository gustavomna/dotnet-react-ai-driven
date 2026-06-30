# CLAUDE.md

Guide for AI agents when working with the code in this repository.

This project uses **React 19 + Vite 8** on the frontend and **.NET 10 Web API** on the backend.

## Harnesses

This repo supports **two AI coding harnesses** as co-equals: **Claude Code** (`claude`) and **auggie** (Augment Code CLI). Both read this `CLAUDE.md` as the single source of truth (auggie auto-loads `CLAUDE.md`, then `AGENTS.md`, at the workspace root). The skills in **`.agents/skills/`** are **harness-neutral** plain markdown and are the single source — never fork or duplicate a skill body per harness.

**Launching:**

```bash
claude                      # Claude Code (interactive)
auggie                      # auggie (interactive)
auggie --print "<prompt>"   # auggie one-shot / non-interactive
```

**Running tasks under a chosen harness:**

```bash
./run-tasks.sh tasks/prd-<feature>                    # claude (default)
./run-tasks.sh tasks/prd-<feature> --harness auggie   # auggie  (or set HARNESS=auggie)
```

**File-layout parity** (add/edit a wrapper in BOTH harness dirs to avoid drift — the shared skill body stays single-source):

| Concern        | Claude Code            | auggie                  | Shared / single-source        |
| -------------- | ---------------------- | ----------------------- | ----------------------------- |
| Slash commands | `.claude/commands/`    | `.augment/commands/`    | —                             |
| Sub-agents     | `.claude/agents/`      | `.augment/agents/`      | —                             |
| Skills         | (via `.agents/skills/`) | (via `.agents/skills/`) | **`.agents/skills/*/SKILL.md`** |
| MCP servers    | `.mcp.json`            | `.augment/mcp.json`     | keep both in sync (same servers) |
| Project rules  | `CLAUDE.md`            | `CLAUDE.md` + `AGENTS.md` | **`CLAUDE.md`**               |

**auggie conventions that differ from Claude Code** (handled in the `.augment/*` wrappers — do not "fix"):

- **No Skill tool.** Claude commands say "activate the X skill"; the `.augment/commands/*.md` instead tell auggie to **read `.agents/skills/<skill>/SKILL.md`** and follow it. `run-tasks.sh` emits the matching directive automatically for `--harness auggie`.
- **Sequential sub-agents.** auggie dispatches sub-agents by name ("Use the `architect-advisor` agent …") and runs them **sequentially**, not via a parallel `Agent` tool. The `council` wrapper accounts for this.
- **Tool names.** Advisor archetypes are kept read-only via `disabled_tools: str-replace-editor, save-file, remove-files, launch-process` (auggie tool names), not Claude's `tools: Read, Grep, …`.
- **Command precedence.** auggie reads `.augment/commands/` before `.claude/commands/`, so the mirrored commands correctly shadow the Claude ones.

> **Drift warning:** adding or renaming a command/agent now means updating **both** `.claude/*` and `.augment/*`. The skill body in `.agents/skills/` remains the single source — only the thin wrappers are mirrored.

### Priorities

- **Always check skills** before implementing — tasks without relevant skills may be invalidated
- **Run checks** before finishing: `npm run lint` (frontend), `npm run typecheck` (frontend), `npm run build` (frontend), `npm run test` (frontend), `dotnet build` (backend), `dotnet test` (backend)
- **Do not use workarounds** — prefer root cause fixes
- **Use `npm install <package>`** to add frontend dependencies
- **Use `dotnet add package <package>`** to add backend dependencies
- **Always use `npm`** as the frontend package manager — never use `yarn`, `pnpm`, or `bun`
- **Never reference Express, Hono, or other Node.js backend frameworks** — the backend uses .NET

### Project Commands

```bash
# Frontend (inside frontend/)
cd frontend
npm run dev              # Development server (Vite)
npm run build            # tsc -b + vite build
npm run lint             # ESLint
npm run typecheck        # tsc -b
npm run test             # Vitest
npm run test:watch       # Tests in watch mode

# Backend (inside backend/)
cd backend
dotnet run               # Start the API server
dotnet build             # Build the project
dotnet test              # Run xUnit tests
dotnet watch run         # Hot-reload development server

# E2E (from root)
npx playwright test      # E2E tests (Playwright)
```

- Frontend runs on port `localhost:5173`
- Backend runs on port `localhost:5080` (HTTP). Port 5000 is avoided because macOS reserves it for the AirPlay Receiver — do not switch back to it.

### Naming convention (English commands, Portuguese skills)

This template mixes two naming layers intentionally. Do not "fix" one to match the other:

- **Slash commands and docs use English names**: `/create-prd`, `/create-techspec`, `/create-tasks`, `/run-task`, `/run-review`, `/run-qa`, `/run-bugfix`.
- **On-disk skill directories use Portuguese names**: `cria-prd`, `cria-techspec`, `criar-tasks`, `executar-task`, `executar-review`, `executar-qa`, `executar-bugfix`.

Both names resolve because Claude Code surfaces each command file in `.claude/commands/` *and* each skill in `.claude/skills/` or `.agents/skills/`. The command files invoke the Portuguese skills by name. `run-tasks.sh` hardcodes `executar-task` for the same reason.

Renaming the skills would touch `run-tasks.sh`, every command file, and invalidate `skills-lock.json` hashes — not worth it. If you add a new skill, pick one language and stay consistent.

### Recommended Stack and Skills

| Area              | Technology                          | Suggested Skill                                                       |
| ----------------- | ----------------------------------- | --------------------------------------------------------------------- |
| React Components  | React 19, hooks                     | `vercel-react-best-practices`, `vercel-composition-patterns`          |
| UI / shadcn       | shadcn/ui (base-nova), Tailwind v4  | `shadcn`, `frontend-design`                                           |
| Backend           | .NET 10, ASP.NET Core Web API       | `dotnet-best-practices`                                               |
| Frontend Tests    | Vitest (unit), Playwright (e2e)     | —                                                                     |
| Backend Tests     | xUnit, FluentAssertions             | —                                                                     |
| Design / UX       | Interface, accessibility            | `ui-ux-pro-max`, `web-design-guidelines`                              |
| PRD               | Product requirements                | `create-prd`                                                          |
| Tech Spec         | Technical specification             | `create-techspec`                                                     |
| Tasks             | Task planning                       | `create-tasks`                                                        |
| Implementation    | Task execution                      | `run-task`                                                             |
| Code Review       | Code review                         | `run-review`, `task-review`                                           |
| QA                | Quality Assurance                   | `run-qa`                                                               |
| Bugfix            | Bug fixing                          | `run-bugfix`                                                           |
| Council Debate    | Multi-agent decision stress-testing | `council` (orchestrates `architect-advisor`, `devils-advocate`, `pragmatic-engineer`, `product-mind`, `security-advocate`, `the-thinker`) |

### Project Structure

```
/                          # Project root
├── playwright.config.ts   # Playwright config (e2e)
├── e2e/
│   └── app.spec.ts        # E2E tests
├── frontend/
│   ├── package.json       # Frontend dependencies
│   ├── src/
│   │   ├── main.tsx              # Entry point (renders App)
│   │   ├── App.tsx               # Root component, defines routes and global providers
│   │   ├── index.css             # Global CSS (Tailwind v4)
│   │   ├── components/           # Reusable application components
│   │   │   ├── ui/               # shadcn components (base-nova) — do not edit manually
│   │   │   └── [domain]/         # Domain components
│   │   ├── pages/                # Page components (one per route)
│   │   ├── hooks/                # Reusable custom hooks
│   │   ├── services/             # External API access functions (fetch wrappers)
│   │   ├── types/                # Shared types and interfaces
│   │   ├── lib/                  # Generic utilities (utils.ts)
│   │   ├── assets/               # Static assets (images, SVGs)
│   │   └── __tests__/            # Frontend unit tests
│   ├── components.json           # shadcn config (style: base-nova, icons: lucide)
│   ├── vite.config.ts            # Vite + React + @tailwindcss/vite
│   └── eslint.config.js          # ESLint flat config
└── backend/
    ├── Backend.sln               # .NET solution file
    ├── src/
    │   └── Backend.Api/          # ASP.NET Core Web API project
    │       ├── Program.cs        # Entry point, middleware, DI configuration
    │       ├── Controllers/      # API controllers
    │       ├── Services/         # Business logic layer
    │       ├── Models/           # Domain models and DTOs
    │       ├── Data/             # Data access and external integrations
    │       └── Backend.Api.csproj
    └── tests/
        └── Backend.Api.Tests/    # xUnit test project
            ├── Controllers/      # Controller integration tests
            ├── Services/         # Service unit tests
            └── Backend.Api.Tests.csproj
```

### React Component Rules

1. **Functional components** — no class components, no `React.FC`
2. **Typed props** — type directly in the function signature
3. **Handle states** — loading, error, and empty
4. **kebab-case** for file names (e.g.: `my-component.tsx`)
5. **Composition** — prefer compound components over many boolean props

### .NET Backend Rules

1. **Controllers** — thin controllers, business logic in services
2. **Dependency Injection** — register services in `Program.cs`, inject via constructor
3. **DTOs** — use records for request/response models
4. **Validation** — use FluentValidation or Data Annotations
5. **Async/await** — all I/O operations must be async
6. **PascalCase** for class names, methods, and properties (C# convention)

### Tests

- **Frontend unit tests**: Vitest with jsdom
- **Frontend libraries**: `@testing-library/react` + `@testing-library/user-event` + `@testing-library/jest-dom`
- **Backend unit tests**: xUnit + FluentAssertions
- **Backend integration tests**: `WebApplicationFactory<Program>` for testing HTTP endpoints
- **E2E**: Playwright (Chromium, Firefox, WebKit) — tests in `e2e/`

### Git

- **Do not run** `git restore`, `git reset`, `git clean` or destructive commands **without explicit user permission**

### Anti-patterns

1. Skipping skill activation
2. Activating only one skill when code touches multiple domains
3. Forgetting verification before marking a task as complete
4. Running destructive git commands without user permission
5. Using workarounds instead of root cause fixes
6. Using `yarn`, `pnpm`, or `bun` instead of `npm` for the frontend
7. Putting business logic in controllers — use services
8. Referencing Node.js backend frameworks (Express, Hono, Fastify) — the backend uses .NET
