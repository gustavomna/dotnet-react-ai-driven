#!/bin/bash
set -euo pipefail

# =============================================================================
# bootstrap.sh — One-shot setup for the AI-Driven Development Starter.
# Installs frontend + e2e npm dependencies and restores the .NET backend.
# Idempotent: safe to run multiple times.
# =============================================================================

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"

# shellcheck source=./_preflight.sh
source "${SCRIPT_DIR}/_preflight.sh"

log_info "Running preflight checks..."
if ! preflight_check_tools node npm dotnet; then
  log_error "Install missing tools and rerun: node (>=20), npm, .NET 10 SDK."
  exit 1
fi
log_success "Preflight OK"

log_info "Installing frontend dependencies..."
(cd "${REPO_ROOT}/frontend" && npm install)

log_info "Installing e2e dependencies..."
(cd "${REPO_ROOT}/e2e" && npm install)

log_info "Restoring .NET solution..."
(cd "${REPO_ROOT}/backend" && dotnet restore)

log_success "Bootstrap complete."
echo ""
log_info "Next steps:"
echo "  Terminal 1:  cd backend && dotnet watch run"
echo "  Terminal 2:  cd frontend && npm run dev"
echo "  Then open:   http://localhost:5173"
