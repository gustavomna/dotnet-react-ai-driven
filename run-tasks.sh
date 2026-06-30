#!/bin/bash
set -euo pipefail

# =============================================================================
# run-tasks.sh — Runs all tasks from a PRD folder via an AI coding harness
# Supports two harnesses: Claude Code (`claude`, default) and auggie (Augment).
# Usage: ./run-tasks.sh tasks/prd-weather-dashboard [options]
# =============================================================================

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

# Colors (TTY only — keep logs free of ANSI escapes when piped to a file)
if [[ -t 1 ]]; then
  RED=$'\033[0;31m'
  GREEN=$'\033[0;32m'
  YELLOW=$'\033[1;33m'
  BLUE=$'\033[0;34m'
  NC=$'\033[0m'
else
  RED='' GREEN='' YELLOW='' BLUE='' NC=''
fi

# Defaults
SKIP_COMPLETED=true
STOP_ON_ERROR=true
MAX_TURNS=""
TASK_TIMEOUT=0
DANGEROUS_MODE=false
LIST_ONLY=false
ONLY_TASK=""
FROM_TASK=""
PRD_DIR=""
ALLOWED_TOOLS="Bash,Edit,Read,Write,Glob,Grep,Agent,Skill"
# Harness selection: claude (default) or auggie. Overridable via HARNESS env var or --harness.
HARNESS="${HARNESS:-claude}"
# auggie MCP config (parallels the project .mcp.json consumed by Claude Code).
AUGGIE_MCP_CONFIG=".augment/mcp.json"
MODEL=""

# Counters / state
TOTAL=0
EXECUTED=0
SKIPPED=0
FAILED=0
LAST_FAILED_TASK=""
LOCK_DIR=""
TRAP_INSTALLED=false

usage() {
  cat <<EOF
Usage: ./run-tasks.sh <prd-folder> [options]

Runs all tasks from a PRD folder sequentially via Claude CLI.

Arguments:
  <prd-folder>                     Path to the PRD folder (e.g.: tasks/prd-weather-dashboard)

Options:
  --harness <claude|auggie>        AI coding harness to use (default: $HARNESS; or set HARNESS env var)
  --no-skip-completed              Execute even tasks already marked as [x]
  --no-stop-on-error               Continue execution even if a task fails
  --max-turns <N>                  Harness turn limit (default: unlimited; omit to use CLI default)
  --model <name>                   Override the harness model (default: harness default)
  --task-timeout <seconds>         Abort an individual task after N seconds (default: no timeout)
  --allowed-tools <csv>            Override Claude --allowedTools (claude only; default: $ALLOWED_TOOLS)
  --dangerously-skip-permissions   Skip Claude CLI permission prompts (claude only)
  --only <N>                       Run only task N (e.g.: --only 3)
  --from <N>                       Start at task N and continue from there
  --list                           Dry-run: list discovered tasks + completion state, then exit
  -h, --help                       Show this message

Examples:
  ./run-tasks.sh tasks/prd-weather-dashboard
  ./run-tasks.sh tasks/prd-weather-dashboard --list
  ./run-tasks.sh tasks/prd-weather-dashboard --harness auggie
  ./run-tasks.sh tasks/prd-weather-dashboard --harness auggie --list
  ./run-tasks.sh tasks/prd-weather-dashboard --only 3
  ./run-tasks.sh tasks/prd-weather-dashboard --from 2 --no-skip-completed
  ./run-tasks.sh tasks/prd-weather-dashboard --task-timeout 1800
  ./run-tasks.sh tasks/prd-weather-dashboard --dangerously-skip-permissions
EOF
  exit 0
}

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[SKIP]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

is_numeric() { [[ "$1" =~ ^[0-9]+$ ]]; }

# Strip leading zeros so arithmetic comparisons don't interpret "08" as octal
strip_leading_zeros() { echo "$((10#$1))"; }

# --- Argument parsing ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --harness)
      HARNESS="${2:-}"; shift 2 ;;
    --no-skip-completed)
      SKIP_COMPLETED=false; shift ;;
    --no-stop-on-error)
      STOP_ON_ERROR=false; shift ;;
    --max-turns)
      MAX_TURNS="${2:-}"; shift 2 ;;
    --model)
      MODEL="${2:-}"; shift 2 ;;
    --task-timeout)
      TASK_TIMEOUT="${2:-}"; shift 2 ;;
    --allowed-tools)
      ALLOWED_TOOLS="${2:-}"; shift 2 ;;
    --dangerously-skip-permissions)
      DANGEROUS_MODE=true; shift ;;
    --only)
      ONLY_TASK="${2:-}"; shift 2 ;;
    --from)
      FROM_TASK="${2:-}"; shift 2 ;;
    --list)
      LIST_ONLY=true; shift ;;
    -h|--help)
      usage ;;
    -*)
      log_error "Unknown flag: $1"; usage ;;
    *)
      if [[ -z "$PRD_DIR" ]]; then
        PRD_DIR="$1"
      else
        log_error "Unexpected extra argument: $1"; usage
      fi
      shift
      ;;
  esac
done

# --- Validation ---
if [[ -z "$PRD_DIR" ]]; then
  log_error "PRD folder not provided."
  usage
fi

# Harness must be one of the supported values
case "$HARNESS" in
  claude|auggie) ;;
  *)
    log_error "--harness expects 'claude' or 'auggie', got: $HARNESS"
    exit 1
    ;;
esac

# Normalize: collapse repeated slashes and strip trailing slashes
PRD_DIR="$(echo "$PRD_DIR" | sed -E 's#/+#/#g; s#/+$##')"

# Strict charset check — defense in depth against shell metacharacters reaching the prompt
if [[ ! "$PRD_DIR" =~ ^[A-Za-z0-9._/-]+$ ]]; then
  log_error "PRD folder contains disallowed characters: $PRD_DIR"
  log_error "Allowed: letters, digits, dot, underscore, slash, hyphen"
  exit 1
fi

if [[ ! -d "$PRD_DIR" ]]; then
  log_error "Folder not found: $PRD_DIR"
  exit 1
fi

for required_file in tasks.md prd.md techspec.md; do
  if [[ ! -f "$PRD_DIR/$required_file" ]]; then
    log_error "Required file not found: $PRD_DIR/$required_file"
    exit 1
  fi
done

# Numeric validation
if [[ -n "$ONLY_TASK" ]] && ! is_numeric "$ONLY_TASK"; then
  log_error "--only expects a non-negative integer, got: $ONLY_TASK"
  exit 1
fi
if [[ -n "$FROM_TASK" ]] && ! is_numeric "$FROM_TASK"; then
  log_error "--from expects a non-negative integer, got: $FROM_TASK"
  exit 1
fi
if [[ -n "$MAX_TURNS" ]] && ! is_numeric "$MAX_TURNS"; then
  log_error "--max-turns expects a positive integer, got: $MAX_TURNS"
  exit 1
fi
if ! is_numeric "$TASK_TIMEOUT"; then
  log_error "--task-timeout expects a non-negative integer (seconds), got: $TASK_TIMEOUT"
  exit 1
fi

if [[ -n "$ONLY_TASK" && -n "$FROM_TASK" ]]; then
  log_error "--only and --from are mutually exclusive"
  exit 1
fi

# --- Preflight ---
# shellcheck source=scripts/_preflight.sh
source "${SCRIPT_DIR}/scripts/_preflight.sh"

# _preflight.sh uses `: "${VAR:=...}"` which re-populates empty color vars.
# Re-apply the TTY guard so piped output stays free of ANSI escapes.
if [[ ! -t 1 ]]; then
  RED='' GREEN='' YELLOW='' BLUE='' NC=''
fi

# Dry-run (--list) inspects files only and never invokes a harness, so skip the
# tool preflight there. Otherwise require the binary for the SELECTED harness only.
if [[ "$LIST_ONLY" != true ]]; then
  if ! preflight_check_tools node dotnet "$HARNESS"; then
    if [[ "$HARNESS" == "auggie" ]]; then
      log_error "Install missing tools and rerun. auggie CLI: npm install -g @augmentcode/auggie"
    else
      log_error "Install missing tools and rerun. Claude CLI: npm install -g @anthropic-ai/claude-code"
    fi
    exit 1
  fi
fi

# Detect a usable timeout binary (Linux: timeout; macOS w/ coreutils: gtimeout)
TIMEOUT_CMD=""
if [[ "$TASK_TIMEOUT" -gt 0 ]]; then
  if command -v timeout &>/dev/null; then
    TIMEOUT_CMD="timeout"
  elif command -v gtimeout &>/dev/null; then
    TIMEOUT_CMD="gtimeout"
  else
    log_warn "--task-timeout set but no 'timeout'/'gtimeout' on PATH; ignoring (brew install coreutils to enable)"
    TASK_TIMEOUT=0
  fi
fi

# --- Discover tasks ---
TASK_FILES=()
for f in "$PRD_DIR"/*_task.md; do
  [[ -f "$f" ]] || continue
  basename_f=$(basename "$f")
  if [[ "$basename_f" =~ ^[0-9]+_task\.md$ ]]; then
    TASK_FILES+=("$f")
  fi
done

if [[ ${#TASK_FILES[@]} -eq 0 ]]; then
  log_error "No tasks found in $PRD_DIR (pattern: N_task.md)"
  exit 1
fi

# Version-sort by full path; works regardless of directory depth
IFS=$'\n' TASK_FILES=($(printf '%s\n' "${TASK_FILES[@]}" | sort -V))
unset IFS

TOTAL=${#TASK_FILES[@]}
log_info "Found $TOTAL task(s) in $PRD_DIR"
echo ""

# --- Helpers that depend on PRD_DIR / flags ---
is_task_completed() {
  local task_num
  task_num="$(strip_leading_zeros "$1")"
  # Anchor the trailing position so task 1 doesn't match "10.0"
  grep -qE "^[[:space:]]*-[[:space:]]*\[x\][[:space:]]*${task_num}\.0([^0-9]|$)" \
    "$PRD_DIR/tasks.md" 2>/dev/null
}

should_filter_task() {
  local task_num
  task_num="$(strip_leading_zeros "$1")"
  if [[ -n "$ONLY_TASK" ]]; then
    [[ "$task_num" -ne "$(strip_leading_zeros "$ONLY_TASK")" ]] && return 0
  fi
  if [[ -n "$FROM_TASK" ]]; then
    [[ "$task_num" -lt "$(strip_leading_zeros "$FROM_TASK")" ]] && return 0
  fi
  return 1
}

print_summary() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo -e "${BLUE}SUMMARY${NC}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo -e "  Total:    $TOTAL"
  echo -e "  Executed: ${GREEN}$EXECUTED${NC}"
  echo -e "  Skipped:  ${YELLOW}$SKIPPED${NC}"
  echo -e "  Failed:   ${RED}$FAILED${NC}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  if [[ -n "$LAST_FAILED_TASK" ]]; then
    echo -e "${YELLOW}Resume with:${NC} $0 $PRD_DIR --from $(strip_leading_zeros "$LAST_FAILED_TASK")"
    echo ""
  fi
}

cleanup() {
  local code=$?
  if [[ -n "$LOCK_DIR" && -d "$LOCK_DIR" ]]; then
    rmdir "$LOCK_DIR" 2>/dev/null || true
  fi
  print_summary
  exit "$code"
}

# --- Dry-run: show effective plan and exit (no lock, no trap) ---
if [[ "$LIST_ONLY" == true ]]; then
  log_info "Dry-run mode (--list). No $HARNESS invocations will be made."
  printf "\n  %-4s  %-10s  %s\n" "#" "STATE" "FILE"
  printf "  %-4s  %-10s  %s\n"   "----" "----------" "----"
  for task_file in "${TASK_FILES[@]}"; do
    basename_f=$(basename "$task_file")
    task_num="${basename_f%%_task.md}"
    if should_filter_task "$task_num"; then
      state="filtered"
    elif is_task_completed "$task_num"; then
      state="completed"
    else
      state="pending"
    fi
    printf "  %-4s  %-10s  %s\n" "$task_num" "$state" "$task_file"
  done
  echo ""
  exit 0
fi

# --- Lock against concurrent runs (mkdir is atomic, portable to macOS) ---
LOCK_DIR="$PRD_DIR/.runlock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log_error "Another run-tasks.sh appears to be running for $PRD_DIR"
  log_error "If you are certain no other run is active, remove the lock manually: rmdir $LOCK_DIR"
  LOCK_DIR=""  # avoid removing someone else's lock from the trap
  exit 1
fi
trap cleanup EXIT
TRAP_INSTALLED=true

# Per-task log directory
LOG_DIR="$PRD_DIR/.runlogs"
mkdir -p "$LOG_DIR"

# --- Prompt template ---
# Quoted heredoc delimiter ('PROMPT_EOF') disables ALL expansion: no $var, no $(cmd), no `cmd`.
# Placeholders are substituted later via bash parameter expansion, which does NOT execute commands.
PROMPT_TEMPLATE=$(cat <<'PROMPT_EOF'
You are an AI assistant responsible for correctly implementing tasks.

__SKILL_DIRECTIVE__

Identify and load the skills necessary to execute the task based on the technologies used.

YOU MUST start the implementation right after planning.

Use Context7 MCP to analyze the documentation for the language, frameworks, and libraries involved in the implementation.

After completing the task, mark it as complete in tasks.md.

ALWAYS RUN the task-reviewer at the end.

Implement task __TASK_NUM__ from the PRD located in __PRD_DIR__.
- Task file: __PRD_DIR__/__TASK_NUM___task.md
- PRD: __PRD_DIR__/prd.md
- Tech Spec: __PRD_DIR__/techspec.md
- Tasks: __PRD_DIR__/tasks.md
PROMPT_EOF
)

# How to load the run-task skill differs per harness:
#  - Claude Code has a Skill tool that resolves the skill by name.
#  - auggie has no Skill tool, so it must read the SKILL.md file directly.
if [[ "$HARNESS" == "auggie" ]]; then
  SKILL_DIRECTIVE="Read .agents/skills/run-task/SKILL.md and follow its procedure EXACTLY for setup, analysis, planning, implementation, and review. When reviewing at the end, also read .agents/skills/task-review/SKILL.md."
else
  SKILL_DIRECTIVE="Activate and follow the run-task skill to guide the entire implementation process. The skill contains the complete procedure for setup, analysis, planning, implementation, and review."
fi

# --- Main loop ---
for task_file in "${TASK_FILES[@]}"; do
  basename_f=$(basename "$task_file")
  task_num="${basename_f%%_task.md}"

  if should_filter_task "$task_num"; then
    continue
  fi

  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  log_info "Task $task_num — $task_file"

  if [[ "$SKIP_COMPLETED" == true ]] && is_task_completed "$task_num"; then
    log_warn "Task $task_num already complete — skipping"
    SKIPPED=$((SKIPPED + 1))
    echo ""
    continue
  fi

  PROMPT="${PROMPT_TEMPLATE//__TASK_NUM__/$task_num}"
  PROMPT="${PROMPT//__PRD_DIR__/$PRD_DIR}"
  PROMPT="${PROMPT//__SKILL_DIRECTIVE__/$SKILL_DIRECTIVE}"

  # Build the harness command. Claude-only flags (--allowedTools,
  # --dangerously-skip-permissions) have no auggie equivalent and are skipped there.
  if [[ "$HARNESS" == "auggie" ]]; then
    HARNESS_CMD=(
      auggie
      --print "$PROMPT"
    )
    if [[ -f "$AUGGIE_MCP_CONFIG" ]]; then
      HARNESS_CMD+=(--mcp-config "$AUGGIE_MCP_CONFIG")
    fi
    if [[ -n "$MAX_TURNS" ]]; then
      HARNESS_CMD+=(--max-turns "$MAX_TURNS")
    fi
    if [[ -n "$MODEL" ]]; then
      HARNESS_CMD+=(--model "$MODEL")
    fi
  else
    HARNESS_CMD=(
      claude
      -p "$PROMPT"
      --allowedTools "$ALLOWED_TOOLS"
      --verbose
    )
    if [[ -n "$MAX_TURNS" ]]; then
      HARNESS_CMD+=(--max-turns "$MAX_TURNS")
    fi
    if [[ -n "$MODEL" ]]; then
      HARNESS_CMD+=(--model "$MODEL")
    fi
    if [[ "$DANGEROUS_MODE" == true ]]; then
      HARNESS_CMD+=(--dangerously-skip-permissions)
    fi
  fi

  if [[ "$TASK_TIMEOUT" -gt 0 && -n "$TIMEOUT_CMD" ]]; then
    HARNESS_CMD=("$TIMEOUT_CMD" "$TASK_TIMEOUT" "${HARNESS_CMD[@]}")
  fi

  log_file="$LOG_DIR/${task_num}_$(date +%Y%m%d-%H%M%S).log"
  log_info "Running $HARNESS for task $task_num... (log: $log_file)"
  echo ""

  # Tee output to a per-task log; PIPESTATUS[0] preserves the harness's real exit code.
  set +e
  "${HARNESS_CMD[@]}" 2>&1 | tee "$log_file"
  exit_code=${PIPESTATUS[0]}
  set -e

  if [[ $exit_code -eq 0 ]]; then
    log_success "Task $task_num completed successfully"
    EXECUTED=$((EXECUTED + 1))
  else
    if [[ $exit_code -eq 124 && -n "$TIMEOUT_CMD" ]]; then
      log_error "Task $task_num timed out after ${TASK_TIMEOUT}s"
    else
      log_error "Task $task_num failed (exit code: $exit_code)"
    fi
    FAILED=$((FAILED + 1))
    LAST_FAILED_TASK="$task_num"

    if [[ "$STOP_ON_ERROR" == true ]]; then
      log_error "Stopping execution (use --no-stop-on-error to continue)"
      break
    fi
  fi

  echo ""
done

# Summary + lock cleanup happen in the EXIT trap.
if [[ $FAILED -gt 0 ]]; then
  exit 1
fi
exit 0
