# CLAUDE.md

Guide for AI agents when working with the code in this repository.

This project uses **React 19 + Vite 8** on the frontend and **.NET 10 Web API** on the backend.

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
- Backend runs on port `localhost:5000` (HTTP) / `localhost:5001` (HTTPS)

### Recommended Stack and Skills

| Area              | Technology                          | Suggested Skill                                                       |
| ----------------- | ----------------------------------- | --------------------------------------------------------------------- |
| React Components  | React 19, hooks                     | `vercel-react-best-practices`, `vercel-composition-patterns`          |
| UI / shadcn       | shadcn/ui (base-nova), Tailwind v4  | `shadcn`, `frontend-design`                                           |
| Backend           | .NET 10, ASP.NET Core Web API       | `dotnet`                                                              |
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
