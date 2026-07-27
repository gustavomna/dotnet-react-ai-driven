#!/bin/bash
set -euo pipefail

# =============================================================================
# install-qa-agent.sh — Installs the QA Agent into a repository in one command.
# Places the agent definition, the slash command, both skill bundles
# (qa-agent, a11y-testing) and the run-qa-agent.sh runner where Claude Code and
# auggie discover them.
# Idempotent: running it twice is a no-op the second time.
# Usage: ./scripts/install-qa-agent.sh [target-repo] [options]
# =============================================================================

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
SRC_ROOT="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"

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
TARGET_ARG=""
TARGET_ROOT=""
HARNESS="both"
MODE=""            # resolved later: symlink | copy
MODE_EXPLICIT=false
FORCE=false
DRY_RUN=false
SELF_INSTALL=false

# The two skill bundles. .agents/skills/ stays the single source; .claude/skills/
# holds relative symlinks into it, exactly like every other skill in this template.
BUNDLES=(qa-agent a11y-testing)

# Executables copied into the target so the runner the final message points at actually
# exists there. Order matters only for readability of the plan table.
#
# Why copied and never symlinked: run-qa-agent.sh derives SCRIPT_DIR from
# "${BASH_SOURCE[0]}" without resolving the file's own symlink, so an installed symlink
# still resolves SCRIPT_DIR to the *target* repository — it gains nothing and leaves the
# target depending on a foreign checkout. Copying keeps the target self-contained.
#
# scripts/_preflight.sh rides along because run-qa-agent.sh sources
# "${SCRIPT_DIR}/scripts/_preflight.sh" unconditionally; without it the copied runner
# aborts on its first line of preflight.
SCRIPTS_SRC_REL=(run-qa-agent.sh scripts/_preflight.sh)

# Plan tables (parallel arrays — bash 3.2 on macOS has no associative arrays)
PLAN_KIND=()
PLAN_SRC=()
PLAN_DEST=()
PLAN_ACTION=()

# Strict charset — defense in depth, same rule as run-tasks.sh
CHARSET_PATH='^[A-Za-z0-9._/-]+$'

usage() {
  cat <<EOF
Usage: ./scripts/install-qa-agent.sh [target-repo] [options]

Installs the QA Agent into a repository: both skill bundles, the agent definition, the
/qa-agent slash command, and the run-qa-agent.sh runner, placed where each harness
discovers them.

Arguments:
  [target-repo]                    Repository to install into (default: $SRC_ROOT)

Options:
  --harness <claude|auggie|both>   Which harness wrappers to install (default: $HARNESS)
  --mode <symlink|copy>            How the skill bundles are placed (default: symlink when the
                                   target is this repo or on the same filesystem, copy otherwise)
  --force                          Overwrite existing files that differ from the source
  --dry-run                        Print the full plan and change nothing
  -h, --help                       Show this message

What gets installed:
  <target>/.agents/skills/qa-agent           skill bundle (single source)
  <target>/.agents/skills/a11y-testing       skill bundle (single source)
  <target>/run-qa-agent.sh                   headless/CI round runner (copied, mode 0755)
  <target>/scripts/_preflight.sh             shared preflight helpers the runner sources
  <target>/.claude/skills/qa-agent           relative symlink -> ../../.agents/skills/qa-agent
  <target>/.claude/skills/a11y-testing       relative symlink -> ../../.agents/skills/a11y-testing
  <target>/.claude/agents/qa-agent.md        Claude Code agent definition
  <target>/.claude/commands/qa-agent.md      /qa-agent slash command (Claude Code)
  <target>/.augment/agents/qa-agent.md       auggie agent definition
  <target>/.augment/commands/qa-agent.md     /qa-agent slash command (auggie)

Notes:
  The .claude/skills entries are always relative symlinks into .agents/skills, so the skill
  body stays single-source. --mode applies to the bundles themselves; the four wrapper
  markdown files are always copied so the target repository stays self-contained.

  run-qa-agent.sh and scripts/_preflight.sh are always copied and never symlinked, whatever
  --mode and --harness say: the runner drives both harnesses, and it resolves its own paths
  relative to where the file sits, so a symlink would point it back at the target repository
  anyway while making the target depend on this checkout.

Examples:
  ./scripts/install-qa-agent.sh
  ./scripts/install-qa-agent.sh --dry-run
  ./scripts/install-qa-agent.sh /path/to/other-repo
  ./scripts/install-qa-agent.sh /path/to/other-repo --mode copy
  ./scripts/install-qa-agent.sh /path/to/other-repo --harness auggie
  ./scripts/install-qa-agent.sh /path/to/other-repo --force
EOF
  # usage 1 is used for argument errors so a mistyped flag never exits successfully;
  # plain usage (0) is reserved for an explicit --help.
  exit "${1:-0}"
}

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[SKIP]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

# Normalize: collapse repeated slashes and strip trailing slashes
normalize_path() { echo "$1" | sed -E 's#/+#/#g; s#/+$##'; }

# --- Argument parsing ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --harness)
      HARNESS="${2:-}"; shift 2 ;;
    --mode)
      MODE="${2:-}"; MODE_EXPLICIT=true; shift 2 ;;
    --force)
      FORCE=true; shift ;;
    --dry-run)
      DRY_RUN=true; shift ;;
    -h|--help)
      usage ;;
    -*)
      log_error "Unknown flag: $1"; usage 1 ;;
    *)
      if [[ -z "$TARGET_ARG" ]]; then
        TARGET_ARG="$1"
      else
        log_error "Unexpected extra argument: $1"; usage 1
      fi
      shift
      ;;
  esac
done

# --- Validation ---
case "$HARNESS" in
  claude|auggie|both) ;;
  *)
    log_error "--harness expects 'claude', 'auggie' or 'both', got: $HARNESS"
    exit 1
    ;;
esac

if [[ "$MODE_EXPLICIT" == true ]]; then
  case "$MODE" in
    symlink|copy) ;;
    *)
      log_error "--mode expects 'symlink' or 'copy', got: $MODE"
      exit 1
      ;;
  esac
fi

if [[ -z "$TARGET_ARG" ]]; then
  TARGET_ROOT="$SRC_ROOT"
else
  TARGET_ARG="$(normalize_path "$TARGET_ARG")"
  if [[ ! "$TARGET_ARG" =~ $CHARSET_PATH ]]; then
    log_error "Target repository path contains disallowed characters: $TARGET_ARG"
    log_error "Allowed: letters, digits, dot, underscore, slash, hyphen"
    exit 1
  fi
  if [[ ! -d "$TARGET_ARG" ]]; then
    log_error "Target repository not found: $TARGET_ARG"
    exit 1
  fi
  TARGET_ROOT="$(cd -- "$TARGET_ARG" &>/dev/null && pwd)"
fi

if [[ "$TARGET_ROOT" == "$SRC_ROOT" ]]; then
  SELF_INSTALL=true
fi

if [[ ! -d "$TARGET_ROOT/.git" && "$SELF_INSTALL" != true ]]; then
  log_warn "Target is not a git repository root (no .git): $TARGET_ROOT"
fi

# --- Preflight ---
# shellcheck source=./_preflight.sh
source "${SCRIPT_DIR}/_preflight.sh"

# _preflight.sh uses `: "${VAR:=...}"` which re-populates empty color vars.
# Re-apply the TTY guard so piped output stays free of ANSI escapes.
if [[ ! -t 1 ]]; then
  RED='' GREEN='' YELLOW='' BLUE='' NC=''
fi

# python3 runs the bundled QA CLI; it is the only hard requirement for installation.
if ! preflight_check_tools python3; then
  log_error "Install Python 3.9 or newer and rerun."
  exit 1
fi

# --- Resolve the placement mode ---
# Symlinks keep one editable copy of a bundle; copies make the target self-contained.
device_id() {
  local probe="$1"
  stat -f '%d' "$probe" 2>/dev/null || stat -c '%d' "$probe" 2>/dev/null || echo "unknown"
}

if [[ "$MODE_EXPLICIT" != true ]]; then
  if [[ "$SELF_INSTALL" == true ]]; then
    MODE="symlink"
  else
    src_device="$(device_id "$SRC_ROOT")"
    dest_device="$(device_id "$TARGET_ROOT")"
    if [[ "$src_device" != "unknown" && "$src_device" == "$dest_device" ]]; then
      MODE="symlink"
    else
      MODE="copy"
    fi
  fi
fi

# --- Build the plan ---
# kind: bundle  -> directory payload, placed per --mode
#       symlink -> relative symlink, PLAN_SRC holds the literal link target
#       file    -> wrapper markdown, always copied
#       script  -> executable, always copied and forced to mode 0755
add_entry() {
  PLAN_KIND+=("$1")
  PLAN_SRC+=("$2")
  PLAN_DEST+=("$3")
}

for bundle in "${BUNDLES[@]}"; do
  add_entry "bundle" "$SRC_ROOT/.agents/skills/$bundle" "$TARGET_ROOT/.agents/skills/$bundle"
done

# Harness-independent: the runner drives claude and auggie alike, so it is installed
# regardless of --harness.
for script_rel in "${SCRIPTS_SRC_REL[@]}"; do
  add_entry "script" "$SRC_ROOT/$script_rel" "$TARGET_ROOT/$script_rel"
done

if [[ "$HARNESS" == "claude" || "$HARNESS" == "both" ]]; then
  for bundle in "${BUNDLES[@]}"; do
    add_entry "symlink" "../../.agents/skills/$bundle" "$TARGET_ROOT/.claude/skills/$bundle"
  done
  add_entry "file" "$SRC_ROOT/.claude/agents/qa-agent.md"   "$TARGET_ROOT/.claude/agents/qa-agent.md"
  add_entry "file" "$SRC_ROOT/.claude/commands/qa-agent.md" "$TARGET_ROOT/.claude/commands/qa-agent.md"
fi

if [[ "$HARNESS" == "auggie" || "$HARNESS" == "both" ]]; then
  add_entry "file" "$SRC_ROOT/.augment/agents/qa-agent.md"   "$TARGET_ROOT/.augment/agents/qa-agent.md"
  add_entry "file" "$SRC_ROOT/.augment/commands/qa-agent.md" "$TARGET_ROOT/.augment/commands/qa-agent.md"
fi

# --- Resolve the action for every entry ---
# create | ok | overwrite | fix-mode | missing-source
#
# fix-mode is script-only and means "the bytes are already correct, only the executable bit
# is not". It destroys nothing, so unlike overwrite it does not need --force.
#
# Byte-code caches are build output, not content: comparing them would make a second run
# report a difference the moment anything ran the CLI, so they are excluded here and the
# verification step below runs Python with byte-code writing disabled.
DIFF_EXCLUDES=(-x '__pycache__' -x '*.pyc' -x '*.pyo' -x '.DS_Store')

bundles_identical() {
  diff -r -q "${DIFF_EXCLUDES[@]}" "$1" "$2" >/dev/null 2>&1
}

resolve_action() {
  local kind="$1" src="$2" dest="$3"

  case "$kind" in
    symlink)
      if [[ -L "$dest" ]]; then
        if [[ "$(readlink "$dest")" == "$src" ]]; then
          echo "ok"
        else
          echo "overwrite"
        fi
      elif [[ -e "$dest" ]]; then
        echo "overwrite"
      else
        echo "create"
      fi
      ;;
    file)
      if [[ ! -f "$src" ]]; then
        echo "missing-source"
      elif [[ "$src" == "$dest" ]]; then
        echo "ok"
      elif [[ -L "$dest" || -d "$dest" ]]; then
        echo "overwrite"
      elif [[ -f "$dest" ]]; then
        if cmp -s "$src" "$dest"; then echo "ok"; else echo "overwrite"; fi
      else
        echo "create"
      fi
      ;;
    script)
      if [[ ! -f "$src" ]]; then
        echo "missing-source"
      elif [[ "$src" == "$dest" ]]; then
        # Self-install: the source *is* the installed runner. Only its mode can be wrong.
        if [[ -x "$dest" ]]; then echo "ok"; else echo "fix-mode"; fi
      elif [[ -L "$dest" || -d "$dest" ]]; then
        echo "overwrite"
      elif [[ -f "$dest" ]]; then
        if ! cmp -s "$src" "$dest"; then
          echo "overwrite"
        elif [[ -x "$dest" ]]; then
          echo "ok"
        else
          echo "fix-mode"
        fi
      else
        echo "create"
      fi
      ;;
    bundle)
      if [[ ! -d "$src" ]]; then
        echo "missing-source"
      elif [[ "$src" == "$dest" ]]; then
        echo "ok"
      elif [[ "$MODE" == "symlink" ]]; then
        if [[ -L "$dest" ]]; then
          if [[ "$(readlink "$dest")" == "$src" ]]; then echo "ok"; else echo "overwrite"; fi
        elif [[ -e "$dest" ]]; then
          echo "overwrite"
        else
          echo "create"
        fi
      else
        if [[ -L "$dest" ]]; then
          echo "overwrite"
        elif [[ -d "$dest" ]]; then
          if bundles_identical "$src" "$dest"; then echo "ok"; else echo "overwrite"; fi
        elif [[ -e "$dest" ]]; then
          echo "overwrite"
        else
          echo "create"
        fi
      fi
      ;;
    *)
      echo "missing-source"
      ;;
  esac
}

rel_to_target() {
  local p="$1"
  echo "${p#"$TARGET_ROOT"/}"
}

COUNT_CREATE=0
COUNT_OK=0
COUNT_OVERWRITE=0
COUNT_FIXMODE=0
COUNT_MISSING=0

for ((i = 0; i < ${#PLAN_KIND[@]}; i++)); do
  action="$(resolve_action "${PLAN_KIND[$i]}" "${PLAN_SRC[$i]}" "${PLAN_DEST[$i]}")"
  PLAN_ACTION+=("$action")
  case "$action" in
    create)         COUNT_CREATE=$((COUNT_CREATE + 1)) ;;
    ok)             COUNT_OK=$((COUNT_OK + 1)) ;;
    overwrite)      COUNT_OVERWRITE=$((COUNT_OVERWRITE + 1)) ;;
    fix-mode)       COUNT_FIXMODE=$((COUNT_FIXMODE + 1)) ;;
    missing-source) COUNT_MISSING=$((COUNT_MISSING + 1)) ;;
  esac
done

# --- Print the plan ---
echo ""
log_info "Source repository: $SRC_ROOT"
log_info "Target repository: $TARGET_ROOT"
log_info "Harness wrappers:  $HARNESS"
log_info "Bundle placement:  $MODE$([[ "$MODE_EXPLICIT" == true ]] && echo " (explicit)" || echo " (auto)")"
if [[ "$SELF_INSTALL" == true ]]; then
  log_info "Target is the source repository — bundles are verified in place, not copied."
fi
echo ""
printf "  %-14s  %-8s  %s\n" "ACTION" "KIND" "PATH"
printf "  %-14s  %-8s  %s\n" "--------------" "--------" "----"
for ((i = 0; i < ${#PLAN_KIND[@]}; i++)); do
  detail="$(rel_to_target "${PLAN_DEST[$i]}")"
  if [[ "${PLAN_KIND[$i]}" == "symlink" ]]; then
    detail="$detail -> ${PLAN_SRC[$i]}"
  elif [[ "${PLAN_KIND[$i]}" == "bundle" && "$MODE" == "symlink" && "$SELF_INSTALL" != true ]]; then
    detail="$detail -> ${PLAN_SRC[$i]}"
  elif [[ "${PLAN_KIND[$i]}" == "script" && "$SELF_INSTALL" != true ]]; then
    detail="$detail (copy, mode 0755)"
  fi
  printf "  %-14s  %-8s  %s\n" "${PLAN_ACTION[$i]}" "${PLAN_KIND[$i]}" "$detail"
done
echo ""

# --- Refuse to clobber anything that differs, unless --force ---
if [[ $COUNT_OVERWRITE -gt 0 && "$FORCE" != true ]]; then
  log_error "$COUNT_OVERWRITE existing path(s) differ from the source. Refusing to overwrite:"
  for ((i = 0; i < ${#PLAN_KIND[@]}; i++)); do
    if [[ "${PLAN_ACTION[$i]}" == "overwrite" ]]; then
      log_error "  would overwrite: ${PLAN_DEST[$i]}"
    fi
  done
  log_error "Rerun with --force to replace them, or move them aside first."
  exit 1
fi

if [[ $COUNT_MISSING -gt 0 ]]; then
  for ((i = 0; i < ${#PLAN_KIND[@]}; i++)); do
    if [[ "${PLAN_ACTION[$i]}" == "missing-source" ]]; then
      if [[ "$DRY_RUN" == true ]]; then
        log_warn "Source not present yet: ${PLAN_SRC[$i]}"
      else
        log_error "Source not found: ${PLAN_SRC[$i]}"
      fi
    fi
  done
  if [[ "$DRY_RUN" != true ]]; then
    log_error "The QA Agent source tree in $SRC_ROOT is incomplete. Nothing was installed."
    exit 1
  fi
fi

if [[ "$DRY_RUN" == true ]]; then
  log_info "Dry-run mode (--dry-run). Nothing was written."
  log_info "Plan: $COUNT_CREATE to create, $COUNT_OVERWRITE to overwrite, $COUNT_FIXMODE to chmod 0755, $COUNT_OK already correct, $COUNT_MISSING missing source."
  exit 0
fi

# --- Apply ---
# Never remove anything outside the target repository, whatever the plan says.
safe_remove() {
  local victim="$1"
  case "$victim" in
    "$TARGET_ROOT"/*) ;;
    *)
      log_error "Refusing to remove a path outside the target repository: $victim"
      exit 1
      ;;
  esac
  rm -rf -- "$victim"
}

APPLIED=0
for ((i = 0; i < ${#PLAN_KIND[@]}; i++)); do
  kind="${PLAN_KIND[$i]}"
  src="${PLAN_SRC[$i]}"
  dest="${PLAN_DEST[$i]}"
  action="${PLAN_ACTION[$i]}"

  if [[ "$action" == "ok" ]]; then
    continue
  fi

  # Content is already correct — only the executable bit is missing. Never re-copy here:
  # in a self-install src and dest are the same file.
  if [[ "$action" == "fix-mode" ]]; then
    chmod 0755 "$dest"
    APPLIED=$((APPLIED + 1))
    log_success "$action $(rel_to_target "$dest")"
    continue
  fi

  mkdir -p "$(dirname -- "$dest")"
  if [[ "$action" == "overwrite" ]]; then
    safe_remove "$dest"
  fi

  case "$kind" in
    symlink)
      ln -s "$src" "$dest"
      ;;
    file)
      cp -- "$src" "$dest"
      ;;
    script)
      # cp alone would carry the source umask through; 0755 is set explicitly so the
      # installed runner is executable no matter how the source tree was checked out.
      cp -- "$src" "$dest"
      chmod 0755 "$dest"
      ;;
    bundle)
      if [[ "$MODE" == "symlink" ]]; then
        ln -s "$src" "$dest"
      else
        cp -R -- "$src" "$dest"
      fi
      ;;
  esac
  APPLIED=$((APPLIED + 1))
  log_success "$action $(rel_to_target "$dest")"
done

if [[ $APPLIED -eq 0 ]]; then
  log_info "Everything was already in place — nothing to do."
fi

# --- Verify ---
echo ""
log_info "Verifying the installation..."
VERIFY_FAILURES=0
for ((i = 0; i < ${#PLAN_KIND[@]}; i++)); do
  dest="${PLAN_DEST[$i]}"
  # -e follows symlinks, so a dangling link fails here exactly as it should.
  if [[ ! -e "$dest" ]]; then
    log_error "Missing after install: $dest"
    VERIFY_FAILURES=$((VERIFY_FAILURES + 1))
  elif [[ "${PLAN_KIND[$i]}" == "script" && ! -x "$dest" ]]; then
    log_error "Installed but not executable: $dest"
    VERIFY_FAILURES=$((VERIFY_FAILURES + 1))
  fi
done

QA_CLI="$TARGET_ROOT/.agents/skills/qa-agent/scripts/qa.py"
CLI_NOTE=""
if [[ ! -f "$QA_CLI" ]]; then
  log_error "QA CLI not found: $QA_CLI"
  VERIFY_FAILURES=$((VERIFY_FAILURES + 1))
elif PYTHONDONTWRITEBYTECODE=1 python3 "$QA_CLI" --version >/dev/null 2>&1; then
  CLI_NOTE="python3 .agents/skills/qa-agent/scripts/qa.py --version ran successfully"
elif PYTHONDONTWRITEBYTECODE=1 python3 "$QA_CLI" --help >/dev/null 2>&1; then
  CLI_NOTE="qa.py answered --help (it does not implement --version)"
  log_warn "$CLI_NOTE"
else
  log_error "The QA CLI did not run: PYTHONDONTWRITEBYTECODE=1 python3 $QA_CLI --version"
  VERIFY_FAILURES=$((VERIFY_FAILURES + 1))
fi

TOTAL_PATHS=${#PLAN_KIND[@]}
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "QA AGENT INSTALLATION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $VERIFY_FAILURES -eq 0 ]]; then
  echo "  Result:  PASS"
  echo "  Paths:   all $TOTAL_PATHS expected paths are present"
  echo "  CLI:     $CLI_NOTE"
  echo "  Target:  $TARGET_ROOT"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
  echo "  Run a round with:  cd $TARGET_ROOT && ./run-qa-agent.sh --dry-run"
  echo "  Or from a harness: /qa-agent"
  echo ""
  exit 0
fi

echo "  Result:  FAIL"
echo "  Checks:  $VERIFY_FAILURES failed ($TOTAL_PATHS expected paths plus the CLI check)"
echo "  Target:  $TARGET_ROOT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Read the [ERROR] lines above: each names the path that is missing or unusable."
echo ""
exit 1
