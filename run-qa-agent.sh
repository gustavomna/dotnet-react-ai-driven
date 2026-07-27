#!/bin/bash
set -euo pipefail

# =============================================================================
# run-qa-agent.sh — Runs one QA round via an AI coding harness
# Supports two harnesses: Claude Code (`claude`, default) and auggie (Augment).
# Sibling of run-tasks.sh: same prompt-building, locking and logging discipline.
# Usage: ./run-qa-agent.sh [scope-path] [options]
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
# Harness selection: claude (default) or auggie. Overridable via HARNESS env var or --harness.
HARNESS="${HARNESS:-claude}"
# auggie MCP config (parallels the project .mcp.json consumed by Claude Code).
AUGGIE_MCP_CONFIG=".augment/mcp.json"
MODEL=""
MAX_TURNS=""
TASK_TIMEOUT=0
ALLOWED_TOOLS="Bash,Edit,Read,Write,Glob,Grep,Agent,Skill"
# Tracked separately from the value so the default never triggers the auggie warning below:
# only a tool restriction the user actually asked for is worth telling them was ignored.
ALLOWED_TOOLS_EXPLICIT=false
DANGEROUS_MODE=false
AUDIT_MODE=false
HEADLESS=false
DRY_RUN=false
REF_RANGE=""
BASE_BRANCH=""

# Repeatable scope inputs
SCOPE_PATHS=()
REQUIREMENT_DOCS=()
PACKAGES=()
LAYERS=()

# Output layout (relative to the current working directory, which is the repo under QA)
QA_DIR="qa"
LOG_DIR="$QA_DIR/.runlogs"
LOCK_DIR=""

# Bundle locations
QA_BUNDLE_REL=".agents/skills/qa-agent"
A11Y_BUNDLE_REL=".agents/skills/a11y-testing"
QA_CLI=""

# Strict charsets — defense in depth against shell metacharacters reaching the prompt
CHARSET_PATH='^[A-Za-z0-9._/-]+$'
CHARSET_PACKAGE='^[A-Za-z0-9._@/-]+$'
CHARSET_MODEL='^[A-Za-z0-9._:-]+$'
CHARSET_TOOLS='^[A-Za-z0-9._,-]+$'

usage() {
  cat <<EOF
Usage: ./run-qa-agent.sh [scope-path] [options]

Runs one QA round via an AI coding harness: resolves scope, derives a plan, generates and
executes the unit / integration / e2e / a11y layers, and writes one issue file per failure.

Arguments:
  [scope-path]                     Optional path to scope the round to (same as --path).

Options:
  --harness <claude|auggie>        AI coding harness to use (default: $HARNESS; or set HARNESS env var)
  --path <p>                       Restrict scope to this path (repeatable)
  --ref-range <A...B>              Restrict scope to a git ref range (e.g.: main...HEAD)
  --requirements <file>            Requirements document to derive criteria from (repeatable)
  --base <branch>                  Base branch for the diff scope (default: repository default branch)
  --package <name>                 Restrict scope to a monorepo package (repeatable)
  --audit                          Read-only one-off audit: no test generation, no writes to test files
  --layer <name>                   Restrict layers to unit|integration|e2e|a11y (repeatable)
  --headless                       CI mode: no interactive confirmation, machine-readable final line
  --model <name>                   Override the harness model (default: harness default)
  --max-turns <N>                  Harness turn limit (default: unlimited; omit to use CLI default)
  --task-timeout <seconds>         Abort the harness run after N seconds (default: no timeout)
  --allowed-tools <csv>            Override Claude --allowedTools (claude only; default: $ALLOWED_TOOLS)
  --dangerously-skip-permissions   Skip Claude CLI permission prompts (claude only)
  --dry-run                        Print the resolved prompt and the detect/scope JSON, then exit
  -h, --help                       Show this message

Exit codes:
  0  The latest round reports the verdict PASS
  1  The latest round reports the verdict FAIL, no summary.json was produced, or the harness failed

Examples:
  ./run-qa-agent.sh
  ./run-qa-agent.sh frontend/src/components
  ./run-qa-agent.sh --ref-range main...HEAD
  ./run-qa-agent.sh --requirements tasks/prd-weather-dashboard/prd.md
  ./run-qa-agent.sh --path frontend/src --layer unit --layer a11y
  ./run-qa-agent.sh --audit --headless
  ./run-qa-agent.sh --harness auggie --base main
  ./run-qa-agent.sh --dry-run --package frontend
  ./run-qa-agent.sh --headless --task-timeout 3600 --dangerously-skip-permissions
EOF
  # This script is a CI gate, so a mistyped flag must never look like a passing round:
  # usage 1 is used for argument errors, plain usage (0) only for an explicit --help.
  exit "${1:-0}"
}

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[SKIP]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

is_numeric() { [[ "$1" =~ ^[0-9]+$ ]]; }

# Normalize: collapse repeated slashes and strip trailing slashes
normalize_path() { echo "$1" | sed -E 's#/+#/#g; s#/+$##'; }

# validate_value <label> <value> <regex>
validate_value() {
  local label="$1" value="$2" pattern="$3"
  if [[ -z "$value" ]]; then
    log_error "$label expects a value"
    exit 1
  fi
  if [[ ! "$value" =~ $pattern ]]; then
    log_error "$label contains disallowed characters: $value"
    log_error "Allowed pattern: $pattern"
    exit 1
  fi
}

# --- Argument parsing ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --harness)
      HARNESS="${2:-}"; shift 2 ;;
    --path)
      SCOPE_PATHS+=("${2:-}"); shift 2 ;;
    --ref-range)
      REF_RANGE="${2:-}"; shift 2 ;;
    --requirements)
      REQUIREMENT_DOCS+=("${2:-}"); shift 2 ;;
    --base)
      BASE_BRANCH="${2:-}"; shift 2 ;;
    --package)
      PACKAGES+=("${2:-}"); shift 2 ;;
    --audit)
      AUDIT_MODE=true; shift ;;
    --layer)
      LAYERS+=("${2:-}"); shift 2 ;;
    --headless)
      HEADLESS=true; shift ;;
    --model)
      MODEL="${2:-}"; shift 2 ;;
    --max-turns)
      MAX_TURNS="${2:-}"; shift 2 ;;
    --task-timeout)
      TASK_TIMEOUT="${2:-}"; shift 2 ;;
    --allowed-tools)
      ALLOWED_TOOLS="${2:-}"; ALLOWED_TOOLS_EXPLICIT=true; shift 2 ;;
    --dangerously-skip-permissions)
      DANGEROUS_MODE=true; shift ;;
    --dry-run)
      DRY_RUN=true; shift ;;
    -h|--help)
      usage ;;
    -*)
      log_error "Unknown flag: $1"; usage 1 ;;
    *)
      SCOPE_PATHS+=("$1")
      shift
      ;;
  esac
done

# --- Validation ---

# Harness must be one of the supported values
case "$HARNESS" in
  claude|auggie) ;;
  *)
    log_error "--harness expects 'claude' or 'auggie', got: $HARNESS"
    exit 1
    ;;
esac

# Scope paths: normalized, charset-checked, existence-warned
if [[ ${#SCOPE_PATHS[@]} -gt 0 ]]; then
  NORMALIZED_PATHS=()
  for raw_path in "${SCOPE_PATHS[@]}"; do
    validate_value "--path" "$raw_path" "$CHARSET_PATH"
    normalized="$(normalize_path "$raw_path")"
    validate_value "--path" "$normalized" "$CHARSET_PATH"
    if [[ ! -e "$normalized" ]]; then
      log_warn "Scope path does not exist in the working tree: $normalized"
    fi
    NORMALIZED_PATHS+=("$normalized")
  done
  SCOPE_PATHS=("${NORMALIZED_PATHS[@]}")
fi

# Requirement documents must exist — a typo here silently changes what is verified
if [[ ${#REQUIREMENT_DOCS[@]} -gt 0 ]]; then
  NORMALIZED_DOCS=()
  for raw_doc in "${REQUIREMENT_DOCS[@]}"; do
    validate_value "--requirements" "$raw_doc" "$CHARSET_PATH"
    normalized="$(normalize_path "$raw_doc")"
    validate_value "--requirements" "$normalized" "$CHARSET_PATH"
    if [[ ! -f "$normalized" ]]; then
      log_error "Requirements document not found: $normalized"
      exit 1
    fi
    NORMALIZED_DOCS+=("$normalized")
  done
  REQUIREMENT_DOCS=("${NORMALIZED_DOCS[@]}")
fi

if [[ ${#PACKAGES[@]} -gt 0 ]]; then
  for pkg in "${PACKAGES[@]}"; do
    validate_value "--package" "$pkg" "$CHARSET_PACKAGE"
  done
fi

if [[ ${#LAYERS[@]} -gt 0 ]]; then
  for layer in "${LAYERS[@]}"; do
    case "$layer" in
      unit|integration|e2e|a11y) ;;
      *)
        log_error "--layer expects one of 'unit', 'integration', 'e2e', 'a11y', got: $layer"
        exit 1
        ;;
    esac
  done
fi

if [[ -n "$REF_RANGE" ]]; then
  validate_value "--ref-range" "$REF_RANGE" "$CHARSET_PATH"
  if [[ "$REF_RANGE" != *".."* ]]; then
    log_error "--ref-range expects a git range such as 'main...HEAD', got: $REF_RANGE"
    exit 1
  fi
fi

if [[ -n "$BASE_BRANCH" ]]; then
  validate_value "--base" "$BASE_BRANCH" "$CHARSET_PATH"
fi

if [[ -n "$MODEL" ]]; then
  validate_value "--model" "$MODEL" "$CHARSET_MODEL"
fi

if [[ -n "$ALLOWED_TOOLS" ]]; then
  validate_value "--allowed-tools" "$ALLOWED_TOOLS" "$CHARSET_TOOLS"
fi

if [[ -n "$MAX_TURNS" ]] && ! is_numeric "$MAX_TURNS"; then
  log_error "--max-turns expects a positive integer, got: $MAX_TURNS"
  exit 1
fi
if ! is_numeric "$TASK_TIMEOUT"; then
  log_error "--task-timeout expects a non-negative integer (seconds), got: $TASK_TIMEOUT"
  exit 1
fi

# Claude-only flags are silently dropped from the auggie command line further down, so say
# so here: a user who passed a tool restriction must not believe it took effect.
if [[ "$HARNESS" == "auggie" ]]; then
  if [[ "$DANGEROUS_MODE" == true ]]; then
    log_warn "--dangerously-skip-permissions is a claude-only flag; ignoring it for auggie"
  fi
  if [[ "$ALLOWED_TOOLS_EXPLICIT" == true ]]; then
    log_warn "--allowed-tools is a claude-only flag; ignoring it for auggie (auggie has no tool allowlist, so the restriction is NOT applied)"
  fi
fi

# --- Preflight ---
# shellcheck source=scripts/_preflight.sh
source "${SCRIPT_DIR}/scripts/_preflight.sh"

# _preflight.sh uses `: "${VAR:=...}"` which re-populates empty color vars.
# Re-apply the TTY guard so piped output stays free of ANSI escapes.
if [[ ! -t 1 ]]; then
  RED='' GREEN='' YELLOW='' BLUE='' NC=''
fi

# python3 drives the QA CLI and parses the round summary — it is always required.
# The harness binary is only required for a real run; --dry-run never invokes one.
REQUIRED_TOOLS=(python3)
if [[ "$DRY_RUN" != true ]]; then
  REQUIRED_TOOLS+=("$HARNESS")
fi
if ! preflight_check_tools "${REQUIRED_TOOLS[@]}"; then
  if [[ "$HARNESS" == "auggie" ]]; then
    log_error "Install missing tools and rerun. auggie CLI: npm install -g @augmentcode/auggie"
  else
    log_error "Install missing tools and rerun. Claude CLI: npm install -g @anthropic-ai/claude-code"
  fi
  exit 1
fi

# node and dotnet are checked but never fatal: the QA agent reports a layer whose runtime
# is unavailable as skipped-unavailable rather than refusing to run at all.
for optional_tool in node dotnet; do
  if ! command -v "$optional_tool" &>/dev/null; then
    log_warn "Optional runtime not found on PATH: $optional_tool — layers that need it will report skipped-unavailable"
  fi
done

# --- Resolve the QA CLI bundle ---
# Prefer the bundle installed in the repository under QA; fall back to this script's own
# checkout so the runner still works when pointed at a repo that has not been installed into.
if [[ -f "$QA_BUNDLE_REL/scripts/qa.py" ]]; then
  QA_CLI="$QA_BUNDLE_REL/scripts/qa.py"
elif [[ -f "$SCRIPT_DIR/$QA_BUNDLE_REL/scripts/qa.py" ]]; then
  QA_CLI="$SCRIPT_DIR/$QA_BUNDLE_REL/scripts/qa.py"
  log_warn "Using the QA bundle from $SCRIPT_DIR (this repo has no $QA_BUNDLE_REL)"
else
  QA_CLI="$QA_BUNDLE_REL/scripts/qa.py"
  if [[ "$DRY_RUN" == true ]]; then
    log_warn "QA bundle not found at $QA_BUNDLE_REL — install it with scripts/install-qa-agent.sh"
  else
    log_error "QA bundle not found at $QA_BUNDLE_REL/scripts/qa.py"
    log_error "Install it first: ./scripts/install-qa-agent.sh"
    exit 1
  fi
fi

# The CLI path is interpolated into the prompt, so it gets the same charset treatment.
validate_value "QA CLI path" "$QA_CLI" "$CHARSET_PATH"

if [[ ! -d "$A11Y_BUNDLE_REL" && ! -d "$SCRIPT_DIR/$A11Y_BUNDLE_REL" ]]; then
  log_warn "Accessibility bundle not found at $A11Y_BUNDLE_REL — the a11y layer will have no reference material"
fi

# --- Build the scope flags handed to `qa.py scope` (and echoed in the prompt) ---
SCOPE_ARGS=(--repo .)
SCOPE_FLAGS=""
SCOPE_BLOCK=""
SCOPE_SOURCES=0

append_scope_flag() { SCOPE_FLAGS="${SCOPE_FLAGS}${SCOPE_FLAGS:+ }$1"; }
append_scope_line() { SCOPE_BLOCK="${SCOPE_BLOCK}${SCOPE_BLOCK:+
}$1"; }

if [[ ${#SCOPE_PATHS[@]} -gt 0 ]]; then
  SCOPE_SOURCES=$((SCOPE_SOURCES + 1))
  for p in "${SCOPE_PATHS[@]}"; do
    SCOPE_ARGS+=(--path "$p")
    append_scope_flag "--path $p"
    append_scope_line "- path: $p"
  done
fi
if [[ -n "$REF_RANGE" ]]; then
  SCOPE_SOURCES=$((SCOPE_SOURCES + 1))
  SCOPE_ARGS+=(--ref-range "$REF_RANGE")
  append_scope_flag "--ref-range $REF_RANGE"
  append_scope_line "- ref range: $REF_RANGE"
fi
if [[ -n "$BASE_BRANCH" ]]; then
  SCOPE_ARGS+=(--base "$BASE_BRANCH")
  append_scope_flag "--base $BASE_BRANCH"
  append_scope_line "- base branch: $BASE_BRANCH"
fi
if [[ ${#REQUIREMENT_DOCS[@]} -gt 0 ]]; then
  SCOPE_SOURCES=$((SCOPE_SOURCES + 1))
  for d in "${REQUIREMENT_DOCS[@]}"; do
    SCOPE_ARGS+=(--requirements "$d")
    append_scope_flag "--requirements $d"
    append_scope_line "- requirements: $d"
  done
fi
if [[ ${#PACKAGES[@]} -gt 0 ]]; then
  SCOPE_SOURCES=$((SCOPE_SOURCES + 1))
  for pkg in "${PACKAGES[@]}"; do
    SCOPE_ARGS+=(--package "$pkg")
    append_scope_flag "--package $pkg"
    append_scope_line "- package: $pkg"
  done
fi

if [[ $SCOPE_SOURCES -eq 0 ]]; then
  append_scope_line "- no explicit scope given: use the diff against the repository default branch"
fi
if [[ $SCOPE_SOURCES -gt 1 ]]; then
  append_scope_line "- several sources are given: the intersection wins"
fi

# --- Layer selection ---
LAYER_FLAGS=""
if [[ ${#LAYERS[@]} -gt 0 ]]; then
  LAYER_LINE=""
  for layer in "${LAYERS[@]}"; do
    LAYER_FLAGS="${LAYER_FLAGS} --layer ${layer}"
    LAYER_LINE="${LAYER_LINE}${LAYER_LINE:+, }${layer}"
  done
  LAYER_LINE="$LAYER_LINE (restricted by --layer; the remaining layers are not part of this round)"
else
  LAYER_LINE="unit, integration, e2e, a11y — every layer the stack detection reports as available"
fi

# --- Mode and interaction ---
if [[ "$AUDIT_MODE" == true ]]; then
  MODE_LINE="one-off read-only audit — do NOT generate tests and do NOT create or modify any test file; run the checks that already exist plus the accessibility scan, and report findings only"
else
  MODE_LINE="full round — derive the plan, generate the missing tests into the repository's existing test layout, execute every layer, then report"
fi

if [[ "$HEADLESS" == true ]]; then
  INTERACTION_LINE="headless (CI) — never ask for confirmation; when the plan is ambiguous take the most conservative reading and record the ambiguity in plan.md"
else
  INTERACTION_LINE="interactive — report the detected stack and the derived plan first, and ask for confirmation only where the plan is genuinely ambiguous"
fi

# --- Prompt template ---
# Quoted heredoc delimiter ('PROMPT_EOF') disables ALL expansion: no $var, no $(cmd), no `cmd`.
# Placeholders are substituted later via bash parameter expansion, which does NOT execute commands.
# Keep the body free of apostrophes, backticks and unbalanced parentheses: bash 3.2 (the
# /bin/bash macOS ships) still scans quoting inside a heredoc nested in $( ), and a stray
# apostrophe makes the whole script fail to parse there.
PROMPT_TEMPLATE=$(cat <<'PROMPT_EOF'
You are a QA agent responsible for verifying that a change actually works.

Implementation and self-validation must not come from the same reasoning pass. Your output
is evidence, not an assertion: a test suite in the repository, a run log with per-layer exit
codes, and one findings file per failure.

__SKILL_DIRECTIVE__

Round mode: __MODE_LINE__
Interaction: __INTERACTION_LINE__
Layers: __LAYER_LINE__

Scope for this round:
__SCOPE_BLOCK__

Drive the round through the bundled Python CLI (Python 3, standard library only, no
third-party imports). Every subcommand prints JSON on stdout and progress on stderr:

  python3 __QA_CLI__ detect --repo .
  python3 __QA_CLI__ scope __SCOPE_FLAGS__
  python3 __QA_CLI__ round new
  python3 __QA_CLI__ plan --round <N> --scope <scope.json> --stack <stack.json>
  python3 __QA_CLI__ exec --round <N>__LAYER_FLAGS__
  python3 __QA_CLI__ report --round <N>

If detect reports no test stack at all, stop and report. Adding a test framework to a
project is a human decision, not yours.

Rules that are not negotiable:

- Execute the layers in the order unit, integration, e2e, a11y. A failing layer never stops
  the remaining layers, so one round reports every problem.
- Never weaken a check to make it pass. Deleting a test, skipping a test, disabling an
  accessibility rule, widening a tolerance, loosening an assertion, or broadening an
  exclusion in response to a failure is forbidden. The only permitted response to a failure
  is an issue file.
- Never overwrite a human-authored test. Extend it or add a sibling file, and report the
  collision. Generated tests are written to the working tree and left unstaged.
- Every generated test names the requirement or criterion it covers, is deterministic (no
  wall-clock dependence, no unseeded randomness, no live third-party calls), and is verified
  to fail for the right reason before it counts as coverage.
- A test that only passes on retry is reported as flaky, never as passed, and is at minimum
  severity medium.
- Any change touching UI makes the accessibility layer required. Tags are fixed at wcag2a,
  wcag2aa, wcag22aa, conformance target WCAG 2.2 AA. Say plainly that automated scanning
  catches roughly a third to a half of real accessibility issues; never claim compliance.
- A suppression is valid only with all three parts: an exact target, a reason, and an expiry
  condition. An invalid or expired suppression does not suppress — the check runs anyway and
  the entry is reported.
- A finding whose fingerprint is in qa/baseline.json is pre-existing: severity low, status
  informational, non-blocking. Everything else gates normally.
- A layer whose runtime is unavailable reports skipped-unavailable with a reason. A skipped
  layer never counts toward a pass, so the verdict line reads PASS — INCOMPLETE, never a
  bare PASS.
- Secrets come from the environment and are never written into generated tests, findings, or
  logs.
- Write only under the detected test directories of this repository, the qa/ output
  directory, and new sibling test files. Nothing else.

Findings: one issue_NNN.md per failure, zero-padded to three digits, numbering continuing
from the highest existing issue in the round. Frontmatter keys are exactly status, file,
line, severity, author, source — in that order. The body states the failing assertion,
observed versus expected, the reproducing command, the requirement it traces to, and a
concrete suggested fix. Never combine unrelated problems into one file.

The round is finished only when qa/rounds/<NNN>/summary.json and qa/rounds/<NNN>/summary.md
both exist. End with the verdict as the word PASS or the word FAIL, the per-severity counts,
and the round directory path. Never rely on colour to carry meaning.
PROMPT_EOF
)

# How to load the qa-agent skill differs per harness:
#  - Claude Code has a Skill tool that resolves the skill by name.
#  - auggie has no Skill tool, so it must read the SKILL.md file directly.
if [[ "$HARNESS" == "auggie" ]]; then
  SKILL_DIRECTIVE="Read .agents/skills/qa-agent/SKILL.md and follow its procedure EXACTLY for scope resolution, stack detection, plan derivation, test generation, execution, and findings reporting. For the accessibility layer, also read .agents/skills/a11y-testing/SKILL.md and follow it."
else
  SKILL_DIRECTIVE="Activate and follow the qa-agent skill to guide the entire round. The skill contains the complete procedure for scope resolution, stack detection, plan derivation, test generation, execution, and findings reporting. For the accessibility layer, also activate and follow the a11y-testing skill."
fi

PROMPT="${PROMPT_TEMPLATE//__SKILL_DIRECTIVE__/$SKILL_DIRECTIVE}"
PROMPT="${PROMPT//__MODE_LINE__/$MODE_LINE}"
PROMPT="${PROMPT//__INTERACTION_LINE__/$INTERACTION_LINE}"
PROMPT="${PROMPT//__LAYER_LINE__/$LAYER_LINE}"
PROMPT="${PROMPT//__LAYER_FLAGS__/$LAYER_FLAGS}"
PROMPT="${PROMPT//__SCOPE_BLOCK__/$SCOPE_BLOCK}"
PROMPT="${PROMPT//__SCOPE_FLAGS__/$SCOPE_FLAGS}"
PROMPT="${PROMPT//__QA_CLI__/$QA_CLI}"

# --- Dry-run: show the resolved prompt and what the CLI resolves, then exit ---
if [[ "$DRY_RUN" == true ]]; then
  log_info "Dry-run mode (--dry-run). No $HARNESS invocations will be made."
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "RESOLVED PROMPT"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  printf '%s\n' "$PROMPT"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  if [[ -f "$QA_CLI" ]]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "qa.py detect --repo . --json"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    set +e
    python3 "$QA_CLI" detect --repo . --json
    detect_status=$?
    set -e
    if [[ $detect_status -ne 0 ]]; then
      log_warn "detect exited with code $detect_status"
    fi
    echo ""

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "qa.py scope ${SCOPE_FLAGS:-<defaults>} --json"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    set +e
    python3 "$QA_CLI" scope "${SCOPE_ARGS[@]}" --json
    scope_status=$?
    set -e
    if [[ $scope_status -ne 0 ]]; then
      log_warn "scope exited with code $scope_status (4 means the scope resolved to nothing)"
    fi
    echo ""
  else
    log_warn "Skipping detect/scope: $QA_CLI is not installed yet"
  fi

  log_info "Dry-run complete. Nothing was written."
  exit 0
fi

# --- Interactive confirmation (skipped in --headless) ---
if [[ "$HEADLESS" != true ]]; then
  echo ""
  log_info "Harness:  $HARNESS"
  log_info "Mode:     $([[ "$AUDIT_MODE" == true ]] && echo "audit (read-only)" || echo "full round")"
  log_info "Layers:   $LAYER_LINE"
  log_info "QA CLI:   $QA_CLI"
  log_info "Scope:"
  printf '%s\n' "$SCOPE_BLOCK" | sed 's/^/    /'
  echo ""
  if [[ -t 0 ]]; then
    printf "Proceed with this QA round? [y/N] "
    read -r reply
    case "$reply" in
      [yY]|[yY][eE][sS]) ;;
      *)
        log_error "Aborted at user request — nothing was run."
        exit 1
        ;;
    esac
  else
    log_warn "stdin is not a terminal — proceeding without confirmation (pass --headless to silence this)"
  fi
fi

# --- Detect a usable timeout binary (Linux: timeout; macOS w/ coreutils: gtimeout) ---
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

# --- Lock against concurrent runs (mkdir is atomic, portable to macOS) ---
mkdir -p "$QA_DIR"
LOCK_DIR="$QA_DIR/.runlock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log_error "Another run-qa-agent.sh appears to be running for this repository"
  log_error "If you are certain no other run is active, remove the lock manually: rmdir $LOCK_DIR"
  LOCK_DIR=""  # avoid removing someone else's lock from the trap
  exit 1
fi

cleanup() {
  local code=$?
  if [[ -n "$LOCK_DIR" && -d "$LOCK_DIR" ]]; then
    rmdir "$LOCK_DIR" 2>/dev/null || true
  fi
  exit "$code"
}
trap cleanup EXIT

mkdir -p "$LOG_DIR"

# --- Build the harness command ---
# Claude-only flags (--allowedTools, --dangerously-skip-permissions) have no auggie
# equivalent and are skipped there.
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

RUN_LOG="$LOG_DIR/$(date +%Y%m%d-%H%M%S).log"
log_info "Running $HARNESS for the QA round... (log: $RUN_LOG)"
echo ""

# Tee output to the run log; PIPESTATUS[0] preserves the harness's real exit code.
set +e
"${HARNESS_CMD[@]}" 2>&1 | tee "$RUN_LOG"
harness_exit=${PIPESTATUS[0]}
set -e

echo ""
if [[ $harness_exit -eq 0 ]]; then
  log_success "Harness finished (exit code: 0)"
elif [[ $harness_exit -eq 124 && -n "$TIMEOUT_CMD" ]]; then
  log_error "Harness timed out after ${TASK_TIMEOUT}s"
else
  log_error "Harness failed (exit code: $harness_exit)"
fi

# --- Read the newest round summary ---
# summary.json is the machine gate; it is parsed with python3, never with grep/sed.
# Same bash 3.2 constraint as the prompt heredoc: no apostrophes inside this block, so the
# embedded Python quotes strings with double quotes only.
set +e
SUMMARY_LINE="$(python3 - "$QA_DIR" <<'PY_EOF'
import json
import os
import re
import sys

qa_dir = sys.argv[1] if len(sys.argv) > 1 else "qa"
rounds_dir = os.path.join(qa_dir, "rounds")

KEYS = ("critical", "high", "medium", "low")


def clean(value):
    return re.sub(r"\s+", "_", str(value)) or "unknown"


def emit(verdict, complete, counts, round_id, round_dir, reason=None):
    if reason:
        sys.stderr.write(reason + "\n")
    sys.stdout.write(
        "QA_RESULT verdict=%s complete=%s critical=%d high=%d medium=%d low=%d round=%s dir=%s\n"
        % (
            clean(verdict),
            clean(complete),
            counts[0],
            counts[1],
            counts[2],
            counts[3],
            clean(round_id),
            clean(round_dir),
        )
    )


best = None
if os.path.isdir(rounds_dir):
    for name in sorted(os.listdir(rounds_dir)):
        candidate = os.path.join(rounds_dir, name, "summary.json")
        if not os.path.isfile(candidate):
            continue
        try:
            number = int(name)
        except ValueError:
            continue
        if best is None or number > best[0]:
            best = (number, name, candidate)

if best is None:
    emit(
        "fail",
        "false",
        (0, 0, 0, 0),
        "none",
        "none",
        "No %s/rounds/NNN/summary.json was produced. The round did not complete." % qa_dir,
    )
    sys.exit(1)

_, round_name, summary_path = best
round_dir = "/".join([qa_dir.rstrip("/"), "rounds", round_name])

try:
    with open(summary_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
except (OSError, ValueError) as exc:
    emit(
        "fail",
        "false",
        (0, 0, 0, 0),
        round_name,
        round_dir,
        "Could not read %s: %s" % (summary_path, exc),
    )
    sys.exit(1)

if not isinstance(data, dict):
    emit("fail", "false", (0, 0, 0, 0), round_name, round_dir,
         "%s is not a JSON object." % summary_path)
    sys.exit(1)

verdict = str(data.get("verdict", "fail")).strip().lower()
if verdict not in ("pass", "fail"):
    verdict = "fail"

complete = "true" if data.get("complete") is True else "false"

raw_counts = data.get("counts")
if not isinstance(raw_counts, dict):
    raw_counts = {}
counts = []
for key in KEYS:
    try:
        counts.append(int(raw_counts.get(key, 0)))
    except (TypeError, ValueError):
        counts.append(0)

emit(verdict, complete, tuple(counts), round_name, round_dir)
sys.exit(0 if verdict == "pass" else 1)
PY_EOF
)"
summary_exit=$?
set -e

VERDICT="fail"
COMPLETE="false"
COUNT_CRITICAL=0
COUNT_HIGH=0
COUNT_MEDIUM=0
COUNT_LOW=0
ROUND_ID="none"
ROUND_DIR="none"

if [[ -n "$SUMMARY_LINE" ]]; then
  read -r -a summary_fields <<<"$SUMMARY_LINE"
  for field in "${summary_fields[@]}"; do
    case "$field" in
      verdict=*)  VERDICT="${field#verdict=}" ;;
      complete=*) COMPLETE="${field#complete=}" ;;
      critical=*) COUNT_CRITICAL="${field#critical=}" ;;
      high=*)     COUNT_HIGH="${field#high=}" ;;
      medium=*)   COUNT_MEDIUM="${field#medium=}" ;;
      low=*)      COUNT_LOW="${field#low=}" ;;
      round=*)    ROUND_ID="${field#round=}" ;;
      dir=*)      ROUND_DIR="${field#dir=}" ;;
      *) ;;
    esac
  done
fi

# --- Colour-free summary: PASS and FAIL are written words, never colour alone ---
VERDICT_WORD="FAIL"
if [[ "$VERDICT" == "pass" ]]; then
  VERDICT_WORD="PASS"
  if [[ "$COMPLETE" != "true" ]]; then
    VERDICT_WORD="PASS — INCOMPLETE (at least one layer was skipped)"
  fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "QA ROUND SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Verdict:   $VERDICT_WORD"
echo "  Round:     $ROUND_ID"
echo "  Directory: $ROUND_DIR"
echo "  Run log:   $RUN_LOG"
echo "  Findings:  critical $COUNT_CRITICAL | high $COUNT_HIGH | medium $COUNT_MEDIUM | low $COUNT_LOW"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ "$ROUND_DIR" == "none" ]]; then
  echo "  No summary.json was produced, so the round did not complete. Treated as FAIL."
  echo "  Inspect $RUN_LOG for what the harness did before it stopped."
else
  echo "  Full findings: $ROUND_DIR (summary.md, issue_NNN.md)"
fi
echo ""

# The harness crashing means the round may be partial, so it can never report a pass.
final_exit=0
if [[ "$VERDICT" != "pass" || $summary_exit -ne 0 ]]; then
  final_exit=1
fi
if [[ $harness_exit -ne 0 ]]; then
  final_exit=1
fi

# In --headless mode this record is the final line on stdout. Nothing may print after it.
if [[ "$HEADLESS" == true ]]; then
  printf 'QA_RESULT verdict=%s complete=%s critical=%s high=%s medium=%s low=%s round=%s dir=%s\n' \
    "$VERDICT" "$COMPLETE" "$COUNT_CRITICAL" "$COUNT_HIGH" "$COUNT_MEDIUM" "$COUNT_LOW" \
    "$ROUND_ID" "$ROUND_DIR"
fi

exit "$final_exit"
