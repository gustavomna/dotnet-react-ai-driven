#!/bin/bash
set -euo pipefail

# =============================================================================
# run-tasks.sh — Runs all tasks from a PRD folder via Claude CLI
# Usage: ./run-tasks.sh tasks/prd-weather-dashboard [options]
# =============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

# Defaults
SKIP_COMPLETED=true
STOP_ON_ERROR=true
MAX_TURNS=50
DANGEROUS_MODE=false
LIST_ONLY=false
ONLY_TASK=""
FROM_TASK=""
PRD_DIR=""

# Counters
TOTAL=0
EXECUTED=0
SKIPPED=0
FAILED=0

usage() {
  cat <<EOF
Usage: ./run-tasks.sh <prd-folder> [options]

Runs all tasks from a PRD folder sequentially via Claude CLI.

Arguments:
  <prd-folder>                     Path to the PRD folder (e.g.: tasks/prd-weather-dashboard)

Options:
  --no-skip-completed              Execute even tasks already marked as [x]
  --no-stop-on-error               Continue execution even if a task fails
  --max-turns <N>                  Claude CLI turn limit (default: 50)
  --dangerously-skip-permissions   Skip Claude CLI permission prompts
  --only <N>                       Run only task N (e.g.: --only 3)
  --from <N>                       Start at task N and continue from there
  --list                           Dry-run: list discovered tasks + completion state, then exit
  -h, --help                       Show this message

Examples:
  ./run-tasks.sh tasks/prd-weather-dashboard
  ./run-tasks.sh tasks/prd-weather-dashboard --list
  ./run-tasks.sh tasks/prd-weather-dashboard --only 3
  ./run-tasks.sh tasks/prd-weather-dashboard --from 2 --no-skip-completed
  ./run-tasks.sh tasks/prd-weather-dashboard --dangerously-skip-permissions
EOF
  exit 0
}

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[SKIP]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

# --- Argument parsing ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-skip-completed)
      SKIP_COMPLETED=false
      shift
      ;;
    --no-stop-on-error)
      STOP_ON_ERROR=false
      shift
      ;;
    --max-turns)
      MAX_TURNS="$2"
      shift 2
      ;;
    --dangerously-skip-permissions)
      DANGEROUS_MODE=true
      shift
      ;;
    --only)
      ONLY_TASK="$2"
      shift 2
      ;;
    --from)
      FROM_TASK="$2"
      shift 2
      ;;
    --list)
      LIST_ONLY=true
      shift
      ;;
    -h|--help)
      usage
      ;;
    -*)
      log_error "Unknown flag: $1"
      usage
      ;;
    *)
      if [[ -z "$PRD_DIR" ]]; then
        PRD_DIR="$1"
      else
        log_error "Unexpected extra argument: $1"
        usage
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

PRD_DIR="${PRD_DIR%/}"

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

# --- Preflight: check required tools are on PATH ---
# Load shared preflight helpers (color vars + log_* + preflight_check_tools)
# shellcheck source=scripts/_preflight.sh
source "${SCRIPT_DIR}/scripts/_preflight.sh"

if ! preflight_check_tools node dotnet claude; then
  log_error "Install missing tools and rerun. Claude CLI: npm install -g @anthropic-ai/claude-code"
  exit 1
fi

# --- Discover tasks ---
TASK_FILES=()
for f in "$PRD_DIR"/*_task.md; do
  [[ -f "$f" ]] || continue
  basename_f=$(basename "$f")
  # Exclude review files (*_task_review.md)
  if [[ "$basename_f" =~ ^[0-9]+_task\.md$ ]]; then
    TASK_FILES+=("$f")
  fi
done

if [[ ${#TASK_FILES[@]} -eq 0 ]]; then
  log_error "No tasks found in $PRD_DIR (pattern: N_task.md)"
  exit 1
fi

# Sort numerically
IFS=$'\n' TASK_FILES=($(for f in "${TASK_FILES[@]}"; do echo "$f"; done | sort -t/ -k2 -V))
unset IFS

TOTAL=${#TASK_FILES[@]}
log_info "Found $TOTAL task(s) in $PRD_DIR"
echo ""

# --- Function to check if task is complete ---
is_task_completed() {
  local task_num="$1"
  grep -qE "^[[:space:]]*-[[:space:]]*\[x\][[:space:]]*${task_num}\.0" "$PRD_DIR/tasks.md" 2>/dev/null
}

# --- Dry-run mode: show the plan and exit ---
if [[ "$LIST_ONLY" == true ]]; then
  log_info "Dry-run mode (--list). No Claude CLI invocations will be made."
  printf "\n  %-4s  %-10s  %s\n" "#" "STATE" "FILE"
  printf "  %-4s  %-10s  %s\n"   "----" "----------" "----"
  for task_file in "${TASK_FILES[@]}"; do
    basename_f=$(basename "$task_file")
    task_num="${basename_f%%_task.md}"
    if is_task_completed "$task_num"; then
      state="completed"
    else
      state="pending"
    fi
    printf "  %-4s  %-10s  %s\n" "$task_num" "$state" "$task_file"
  done
  echo ""
  exit 0
fi

# --- Main loop ---
for task_file in "${TASK_FILES[@]}"; do
  basename_f=$(basename "$task_file")
  task_num="${basename_f%%_task.md}"

  # --only: skip every task that isn't exactly N
  if [[ -n "$ONLY_TASK" && "$task_num" != "$ONLY_TASK" ]]; then
    continue
  fi

  # --from: skip tasks with a number below N
  if [[ -n "$FROM_TASK" && "$task_num" -lt "$FROM_TASK" ]]; then
    continue
  fi

  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  log_info "Task $task_num — $task_file"

  # Check if already complete
  if [[ "$SKIP_COMPLETED" == true ]] && is_task_completed "$task_num"; then
    log_warn "Task $task_num already complete — skipping"
    ((SKIPPED++))
    echo ""
    continue
  fi

  # Build prompt
  PROMPT=$(cat <<PROMPT_EOF
You are an AI assistant responsible for correctly implementing tasks.

Activate and follow the executar-task skill to guide the entire implementation process. The skill contains the complete procedure for setup, analysis, planning, implementation, and review.

Identify and load the skills necessary to execute the task based on the technologies used.

YOU MUST start the implementation right after planning.

Use Context7 MCP to analyze the documentation for the language, frameworks, and libraries involved in the implementation.

After completing the task, mark it as complete in tasks.md.

ALWAYS RUN the task-reviewer at the end.

Implement task ${task_num} from the PRD located in ${PRD_DIR}.
- Task file: ${PRD_DIR}/${task_num}_task.md
- PRD: ${PRD_DIR}/prd.md
- Tech Spec: ${PRD_DIR}/techspec.md
- Tasks: ${PRD_DIR}/tasks.md
PROMPT_EOF
)

  # Build claude command
  CLAUDE_CMD=(
    claude
    -p "$PROMPT"
    --allowedTools "Bash,Edit,Read,Write,Glob,Grep,Agent,Skill"
    --max-turns "$MAX_TURNS"
    --verbose
  )

  if [[ "$DANGEROUS_MODE" == true ]]; then
    CLAUDE_CMD+=(--dangerously-skip-permissions)
  fi

  log_info "Running claude for task $task_num..."
  echo ""

  # Execute
  set +e
  "${CLAUDE_CMD[@]}"
  exit_code=$?
  set -e

  if [[ $exit_code -eq 0 ]]; then
    log_success "Task $task_num completed successfully"
    ((EXECUTED++))
  else
    log_error "Task $task_num failed (exit code: $exit_code)"
    ((FAILED++))

    if [[ "$STOP_ON_ERROR" == true ]]; then
      log_error "Stopping execution (use --no-stop-on-error to continue)"
      break
    fi
  fi

  echo ""
done

# --- Summary ---
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}SUMMARY${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  Total:    $TOTAL"
echo -e "  Executed: ${GREEN}$EXECUTED${NC}"
echo -e "  Skipped:  ${YELLOW}$SKIPPED${NC}"
echo -e "  Failed:   ${RED}$FAILED${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ $FAILED -gt 0 ]]; then
  exit 1
fi
