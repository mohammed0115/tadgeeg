#!/bin/bash
# ============================================================
# FinAI — Full Deployment Orchestrator
# Usage: bash deploy_finish.sh [live|dev|test]
#
# Calls all numbered scripts in order.
# Each step is logged. On any failure, deployment stops
# and a rollback checkpoint is offered.
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV="${1:-live}"

ENV_FILE="$SCRIPT_DIR/config/${ENV}.env"
[ -f "$ENV_FILE" ] || {
  echo "❌ Unknown environment: '$ENV'"
  echo "   Usage: bash deploy_finish.sh [live|dev|test]"
  exit 1
}
source "$ENV_FILE"

mkdir -p "$LOG_DIR"
DEPLOY_LOG="$LOG_DIR/deploy_$(date +%Y%m%d_%H%M%S).log"
touch "$DEPLOY_LOG"

log()  { echo "$(date '+%F %T') [$ENV_LABEL] $1" | tee -a "$DEPLOY_LOG"; }
fail() { echo ""; echo "❌ DEPLOYMENT FAILED at: $1"; echo "   Log: $DEPLOY_LOG"; exit 1; }

DEPLOY_START=$(date +%s)
STEP_COUNT=9

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   FinAI — Full Deployment                                 ║"
echo "╠═══════════════════════════════════════════════════════════╣"
echo "║   Environment : $ENV_LABEL                                       "
echo "║   Domain      : https://$DOMAIN_MAIN                           "
echo "║   Branch      : $BRANCH                                        "
echo "║   Server      : $SERVER_IP                                     "
echo "║   Log         : $DEPLOY_LOG                                    "
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# ── Confirmation for live environment ────────────────────────────────────────
if [ "$ENV_NAME" = "live" ]; then
  echo "⚠️  You are deploying to the LIVE environment (tadgeeg.com)"
  echo "   This will restart the production application."
  echo ""
  read -rp "   Type 'yes' to continue: " CONFIRM
  if [ "$CONFIRM" != "yes" ]; then
    echo "Deployment cancelled."
    exit 0
  fi
  echo ""
fi

# ── Create pre-deployment snapshot ────────────────────────────────────────────
SNAPSHOT_DIR="$LOG_DIR/snapshots/$(date +%Y%m%d_%H%M%S)"
if [ -d "$PROJECT_ROOT" ]; then
  log "📸 Creating pre-deployment snapshot..."
  mkdir -p "$SNAPSHOT_DIR"
  git -C "$PROJECT_ROOT" log -1 --format="%H %s" > "$SNAPSHOT_DIR/commit.txt" 2>/dev/null || true
  log "  Snapshot saved to $SNAPSHOT_DIR"
fi

# ── Step runner ────────────────────────────────────────────────────────────────
run_step() {
  local STEP_NUM="$1"
  local STEP_NAME="$2"
  local SCRIPT="$3"

  echo ""
  echo "────────────────────────────────────────────────────"
  echo "  Step $STEP_NUM/$STEP_COUNT — $STEP_NAME"
  echo "────────────────────────────────────────────────────"
  log "▶ Step $STEP_NUM: $STEP_NAME"

  STEP_START=$(date +%s)

  if bash "$SCRIPT_DIR/$SCRIPT" "$ENV" 2>&1 | tee -a "$DEPLOY_LOG"; then
    STEP_END=$(date +%s)
    STEP_SEC=$((STEP_END - STEP_START))
    log "✅ Step $STEP_NUM DONE in ${STEP_SEC}s"
  else
    log "❌ Step $STEP_NUM FAILED: $STEP_NAME"
    fail "Step $STEP_NUM — $STEP_NAME"
  fi
}

# ── Run all steps ──────────────────────────────────────────────────────────────
run_step 1 "Environment Check"        "00_env_check.sh"
run_step 2 "Git Sync"                 "01_git_sync.sh"
run_step 3 "System Setup"             "02_system_setup.sh"
run_step 4 "OCR & AI Setup"           "03_ocr_setup.sh"
run_step 5 "Gunicorn Service"         "04_gunicorn_service.sh"
run_step 6 "Nginx Configuration"      "05_nginx_setup.sh"
run_step 7 "SSL/TLS Certificate"      "06_ssl_setup.sh"
run_step 8 "Monitoring"               "07_monitoring.sh"
run_step 9 "Notifications"            "08_notifications.sh"

# ── Final summary ─────────────────────────────────────────────────────────────
DEPLOY_END=$(date +%s)
ELAPSED=$((DEPLOY_END - DEPLOY_START))
COMMIT=$(git -C "$PROJECT_ROOT" log -1 --format="%h — %s" 2>/dev/null || echo "N/A")

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║  ✅  DEPLOYMENT SUCCESSFUL                                ║"
echo "╠═══════════════════════════════════════════════════════════╣"
printf "║  Environment : %-44s ║\n" "$ENV_LABEL"
printf "║  Domain      : %-44s ║\n" "https://$DOMAIN_MAIN"
printf "║  Commit      : %-44s ║\n" "${COMMIT:0:44}"
printf "║  Duration    : %-44s ║\n" "${ELAPSED}s"
printf "║  Log         : %-44s ║\n" "$DEPLOY_LOG"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

log "🎉 Full deployment completed in ${ELAPSED}s"

# ── Quick service status ──────────────────────────────────────────────────────
echo "Service Status:"
for SVC in "$SERVICE_NAME" "${SERVICE_NAME}_celery" "${SERVICE_NAME}_celerybeat" nginx redis-server; do
  STATUS=$(systemctl is-active "$SVC" 2>/dev/null || echo "not-installed")
  [ "$STATUS" = "active" ] && ICON="✅" || ICON="⚠️ "
  printf "  %s %-35s %s\n" "$ICON" "$SVC" "$STATUS"
done
echo ""
