# Task: Add the auggie (Augment Code CLI) as a second harness — full parity with Claude Code

## Role
You are a senior tooling engineer integrating a second AI coding harness into an existing
Claude Code–native repository. Your job is to make **auggie (Augment Code CLI)** a co-equal
harness alongside Claude Code, with full parity, **without breaking the existing Claude Code path**.

## Background (how this repo is wired today)
- Slash commands: `.claude/commands/*.md` (English names) → invoke skills in `.agents/skills/<skill>/SKILL.md`.
- Skills live in `.agents/skills/` and are **harness-neutral** (plain markdown) — both harnesses can use them. Keep them single-source; do NOT fork or duplicate skill bodies.
- Council archetypes: `.claude/agents/*.md` (architect-advisor, devils-advocate, pragmatic-engineer, product-mind, security-advocate, the-thinker, task-reviewer).
- MCP servers: `.mcp.json` (Context7 for docs, Playwright for E2E).
- Task automation: `run-tasks.sh` calls the `claude` CLI directly — no harness selection.
- `AGENTS.md` delegates to `CLAUDE.md`, the single source of truth.
- Stack: React 19 + Vite (frontend, `frontend/`), .NET 10 Web API (backend, `backend/`). Backend port 5080, frontend 5173.

## Step 0 — Verify, don't assume
1. Confirm auggie is installed: run `auggie --version`. If missing, install per the official docs (`npm install -g @augmentcode/auggie` is the typical path) and note it in the docs you write — do not block on auth.
2. Run `auggie --help` and skim https://docs.augmentcode.com/cli/reference and https://docs.augmentcode.com/cli/overview to confirm the **current** conventions for: custom commands dir, workspace agents dir, MCP config (`--mcp-config` / `settings.json`), and the `--print` flag. If any convention below has changed, follow the docs and note the deviation. Do not invent flags.

## Required work (full parity)

### 1. Project context (auggie reads AGENTS.md + CLAUDE.md automatically)
- Verify `AGENTS.md` cleanly points auggie at `CLAUDE.md`; confirm both load. Add a short top section to `CLAUDE.md` titled "Harnesses" stating the repo supports **both** Claude Code and auggie, and that skills in `.agents/skills/` are harness-neutral. Do not duplicate the full instructions into AGENTS.md — keep CLAUDE.md the single source.

### 2. Mirror slash commands → `.augment/commands/`
- For each file in `.claude/commands/*.md`, create `.augment/commands/<same-name>.md` with auggie YAML frontmatter and a body that points to the **same** `.agents/skills/<skill>/SKILL.md` and forwards `$ARGUMENTS`. Do not copy skill logic inline — reference the skill file so there is one source of truth.
- Cover all of: create-prd, create-techspec, create-tasks, run-task, run-review, run-qa, run-bugfix, council.

### 3. Mirror council archetypes → `.augment/agents/`
- For each `.claude/agents/*.md`, create `.augment/agents/<same-name>.md` adapting the frontmatter to auggie's schema (`tools` / `disabled_tools`; omit both to grant all tools). Keep the persona body identical. Ensure `council` orchestration can dispatch them under auggie (verify auggie's sub-agent invocation mechanism and adjust the council command wording if its dispatch syntax differs from Claude's `Agent` tool).

### 4. MCP parity
- Translate the servers in `.mcp.json` (Context7, Playwright) into auggie's MCP format. Prefer a project-committed `.augment/mcp.json` consumed via `auggie --mcp-config .augment/mcp.json` (so it stays in version control and parallels `.mcp.json`). Document the `~/.augment/settings.json` alternative. Keep `.augment/mcp.json` and `.mcp.json` semantically in sync (same servers/args).

### 5. Harness selection in `run-tasks.sh`
- Add a `--harness <claude|auggie>` flag (default `claude`) and/or `HARNESS` env var, parsed alongside the existing options.
- Build the command per harness:
  - claude (unchanged): `claude -p "$PROMPT" --allowedTools "$ALLOWED_TOOLS" --verbose`
  - auggie: `auggie --print "$PROMPT" --mcp-config .augment/mcp.json` (add `--max-turns`/`--model` only if the existing flags map cleanly; verify against `auggie --help`).
- Reuse the existing logging (`tee` + `PIPESTATUS`), `--task-timeout` (`timeout`/`gtimeout`) wrapper, and `--only`/`--from`/`--list` logic for both harnesses — do not duplicate that machinery.
- Extend the preflight (`scripts/_preflight.sh`) to check the **selected** harness binary (`auggie` when chosen) instead of always requiring `claude`.
- Update `.claude/settings.local.json` allow-list entries if the new invocation form needs them (e.g. an `auggie ...` permission).

### 6. Documentation
- In `CLAUDE.md`, add a "Harnesses" section: how to launch each (`claude` vs `auggie`), how to run tasks with `./run-tasks.sh <prd-dir> --harness auggie`, and the file-layout parity table (`.claude/*` ↔ `.augment/*`, shared `.agents/skills/`, `.mcp.json` ↔ `.augment/mcp.json`).
- Note that adding a new command/agent/skill now means updating **both** harness dirs (or a generator), to prevent drift.

## Constraints (must follow)
- Do NOT break the Claude Code path — `claude` must remain the default and behave exactly as before.
- Keep skills single-source in `.agents/skills/`; mirror only the thin command/agent wrappers.
- Preserve the existing English-command naming and the project's `CLAUDE.md` rules and anti-patterns (thin controllers, npm-only frontend, .NET backend, async I/O, etc.).
- Do NOT run destructive git commands (`git reset/restore/clean`) without explicit permission.
- Prefer root-cause solutions over workarounds; if an auggie convention genuinely conflicts with a Claude one, document the difference instead of hacking around it.

## Verification (run before declaring done)
1. `auggie --version` succeeds.
2. Context: `auggie --print --quiet "In one sentence, what stack does this repo use and what port is the backend on?"` → mentions .NET 10 / React and port 5080 (proves AGENTS.md/CLAUDE.md loaded).
3. Slash command: invoke a mirrored command under auggie (e.g. `/create-prd`) and confirm it loads the matching `.agents/skills/.../SKILL.md`.
4. MCP: confirm auggie lists/uses the Context7 and Playwright servers with `--mcp-config .augment/mcp.json`.
5. Task runner: `./run-tasks.sh tasks/<some-prd-dir> --harness auggie --list` (dry run) shows tasks; then run one real task end-to-end under `--harness auggie`. Re-run with `--harness claude` (or no flag) to confirm the default path is unchanged.
6. Project checks still pass: `cd frontend && npm run lint && npm run typecheck && npm run build && npm run test`; `cd backend && dotnet build && dotnet test`.
7. Summarize what was created/changed and any auggie conventions that differed from this prompt's assumptions.
