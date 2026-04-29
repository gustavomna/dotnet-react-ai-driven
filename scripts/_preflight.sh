#!/bin/bash
# Shared preflight helpers sourced by bootstrap.sh and run-tasks.sh.
# Defines: preflight_check_tools, and the RED/GREEN/YELLOW/BLUE/NC color vars
# plus log_info/log_success/log_warn/log_error if they are not already set.

# Colors (only set if not already defined by the caller)
: "${RED:=\033[0;31m}"
: "${GREEN:=\033[0;32m}"
: "${YELLOW:=\033[1;33m}"
: "${BLUE:=\033[0;34m}"
: "${NC:=\033[0m}"

if ! command -v log_info &>/dev/null; then
  log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
  log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
  log_warn()    { echo -e "${YELLOW}[SKIP]${NC} $1"; }
  log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
fi

# preflight_check_tools tool1 tool2 ...
# Returns 0 if all tools are on PATH, 1 otherwise. Logs one line per missing tool.
preflight_check_tools() {
  local missing=0
  for tool in "$@"; do
    if ! command -v "$tool" &>/dev/null; then
      log_error "Required tool not found on PATH: $tool"
      missing=1
    fi
  done
  return $missing
}
