#!/bin/bash
# ============================================================
# FinAI — Git Auto-Deploy Background Daemon
# Usage: bash git_.sh [start|stop|status|install]
#
# Watches all three branches for changes:
#   master → triggers safe pull request on live server
#   dev    → triggers safe pull request on dev server
#   test   → triggers safe pull request on test server
#
# "Safe pull request" means:
#   1. Fetch origin
#   2. Check if remote is ahead of local
#   3. If yes → log the change + run refresh.sh for that env
#   4. Never force-push or overwrite uncommitted work
#
# Runs as a background process (daemon).
# Install as systemd service with: bash git_.sh install
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:-start}"

# ── Configuration ─────────────────────────────────────────────────────────────
DAEMON_NAME="finai_git_autodeploy"
PID_FILE="/var/run/${DAEMON_NAME}.pid"
LOG_FILE="/var/log/finai/git_autodeploy.log"
POLL_INTERVAL=60          # Check every 60 seconds
LOCK_FILE="/var/lock/${DAEMON_NAME}.lock"

# Branch → Environment mapping
declare -A BRANCH_ENV_MAP=(
  ["master"]="live"
  ["dev"]="dev"
  ["test"]="test"
)

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$PID_FILE")"

# ── Logging ───────────────────────────────────────────────────────────────────
log() {
  echo "$(date '+%F %T') [GIT-AUTODEPLOY] $1" | tee -a "$LOG_FILE"
}

# ── Load env for a given environment ─────────────────────────────────────────
load_env() {
  local ENV="$1"
  local ENV_FILE="$SCRIPT_DIR/config/${ENV}.env"
  [ -f "$ENV_FILE" ] && source "$ENV_FILE" || return 1
}

# ── Check if remote branch has new commits ────────────────────────────────────
has_new_commits() {
  local REPO_DIR="$1"
  local BRANCH="$2"

  cd "$REPO_DIR" || return 1

  # Fetch quietly (timeout 30s)
  timeout 30 git fetch origin "$BRANCH" --quiet 2>/dev/null || return 1

  LOCAL=$(git rev-parse HEAD 2>/dev/null || echo "")
  REMOTE=$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo "")

  [ -n "$LOCAL" ] && [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]
}

# ── Safe deployment for an environment ────────────────────────────────────────
deploy_environment() {
  local ENV="$1"
  local BRANCH="$2"
  local REPO_DIR="$3"

  log "🚀 Change detected on branch [$BRANCH] → deploying [$ENV]..."

  # Create deploy lock to prevent concurrent deploys
  local DEPLOY_LOCK="/var/lock/finai_deploy_${ENV}.lock"
  exec 300>"$DEPLOY_LOCK"
  if ! flock -n 300; then
    log "⏳ [$ENV] Deploy already in progress — skipping"
    return 0
  fi

  local DEPLOY_LOG="/var/log/finai/${ENV}/autodeploy_$(date +%Y%m%d_%H%M%S).log"
  mkdir -p "$(dirname "$DEPLOY_LOG")"

  # Record what commit triggered the deploy
  cd "$REPO_DIR"
  PREV_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
  NEW_COMMIT=$(git rev-parse --short "origin/$BRANCH" 2>/dev/null || echo "unknown")

  log "  $ENV: $PREV_COMMIT → $NEW_COMMIT"

  # Run refresh (git pull + migrate + collectstatic + restart)
  if bash "$SCRIPT_DIR/refresh.sh" "$ENV" >> "$DEPLOY_LOG" 2>&1; then
    log "✅ [$ENV] Auto-deploy SUCCESS ($PREV_COMMIT → $NEW_COMMIT)"
    log "   Log: $DEPLOY_LOG"
  else
    log "❌ [$ENV] Auto-deploy FAILED — check $DEPLOY_LOG"
    # Send alert
    local ENV_FILE="$SCRIPT_DIR/config/${ENV}.env"
    if [ -f "$ENV_FILE" ]; then
      source "$ENV_FILE"
      echo "FinAI [$ENV_LABEL] auto-deploy FAILED at $(date)
Branch: $BRANCH
Commit: $NEW_COMMIT
Log: $DEPLOY_LOG" | mail -s "[FinAI $ENV_LABEL] AUTO-DEPLOY FAILED" "$SSL_EMAIL" 2>/dev/null || true
    fi
  fi
}

# ── Main polling loop (runs as daemon) ────────────────────────────────────────
run_daemon() {
  log "🟢 Git auto-deploy daemon started (PID $$, poll every ${POLL_INTERVAL}s)"
  log "   Watching: master→live, dev→dev, test→test"

  while true; do
    for BRANCH in "${!BRANCH_ENV_MAP[@]}"; do
      ENV="${BRANCH_ENV_MAP[$BRANCH]}"
      ENV_FILE="$SCRIPT_DIR/config/${ENV}.env"

      # Load environment config
      [ -f "$ENV_FILE" ] || continue
      source "$ENV_FILE"

      REPO_DIR="$PROJECT_ROOT"

      # Skip if repo doesn't exist yet
      [ -d "$REPO_DIR/.git" ] || continue

      # Check for new commits
      if has_new_commits "$REPO_DIR" "$BRANCH"; then
        deploy_environment "$ENV" "$BRANCH" "$REPO_DIR"
      fi
    done

    sleep "$POLL_INTERVAL"
  done
}

# ── Control commands ──────────────────────────────────────────────────────────
cmd_start() {
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "⚠️  Git auto-deploy daemon is already running (PID $(cat "$PID_FILE"))"
    return 0
  fi

  echo "🚀 Starting git auto-deploy daemon..."
  run_daemon &
  DAEMON_PID=$!
  echo "$DAEMON_PID" > "$PID_FILE"
  echo "✅ Daemon started (PID $DAEMON_PID)"
  echo "   Log: $LOG_FILE"
}

cmd_stop() {
  if [ ! -f "$PID_FILE" ]; then
    echo "ℹ️  Daemon is not running (no PID file)"
    return 0
  fi
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    rm -f "$PID_FILE"
    echo "✅ Daemon stopped (PID $PID)"
  else
    echo "⚠️  Process $PID not found — cleaning up PID file"
    rm -f "$PID_FILE"
  fi
}

cmd_status() {
  echo ""
  echo "Git Auto-Deploy Daemon Status"
  echo "─────────────────────────────"
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "  Status : ✅ RUNNING (PID $(cat "$PID_FILE"))"
  else
    echo "  Status : ❌ NOT RUNNING"
  fi
  echo "  Log    : $LOG_FILE"
  echo "  Poll   : every ${POLL_INTERVAL}s"
  echo ""
  echo "Recent activity (last 20 lines):"
  tail -n 20 "$LOG_FILE" 2>/dev/null || echo "  (no log yet)"
  echo ""
}

cmd_install() {
  # Install as a systemd service
  UNIT_FILE="/etc/systemd/system/${DAEMON_NAME}.service"
  log "📝 Installing systemd service: $UNIT_FILE"

  cat > "$UNIT_FILE" <<UNIT
[Unit]
Description=FinAI Git Auto-Deploy Daemon
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
ExecStart=/bin/bash $SCRIPT_DIR/git_.sh _daemon
ExecStop=/bin/bash $SCRIPT_DIR/git_.sh stop
Restart=on-failure
RestartSec=30
StandardOutput=append:$LOG_FILE
StandardError=append:$LOG_FILE

# Health: restart if not producing output for 5 minutes
TimeoutStartSec=60
WatchdogSec=300

[Install]
WantedBy=multi-user.target
UNIT

  systemctl daemon-reload
  systemctl enable "${DAEMON_NAME}"
  systemctl restart "${DAEMON_NAME}"
  sleep 2
  systemctl is-active --quiet "${DAEMON_NAME}" \
    && echo "✅ ${DAEMON_NAME} service installed and running" \
    || echo "❌ Service failed to start — check: journalctl -u ${DAEMON_NAME} -n 30"
}

cmd_restart() {
  cmd_stop
  sleep 2
  cmd_start
}

# Internal daemon entry point (called by systemd)
_daemon() { run_daemon; }

# ── Dispatch ──────────────────────────────────────────────────────────────────
case "$ACTION" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_restart ;;
  status)  cmd_status ;;
  install) cmd_install ;;
  _daemon) _daemon ;;
  *)
    echo ""
    echo "FinAI Git Auto-Deploy"
    echo "Usage: bash git_.sh [start|stop|restart|status|install]"
    echo ""
    echo "  start    — Start daemon in background"
    echo "  stop     — Stop running daemon"
    echo "  restart  — Restart daemon"
    echo "  status   — Show daemon status and recent logs"
    echo "  install  — Install as systemd service (recommended for production)"
    echo ""
    echo "Branch → Environment mapping:"
    echo "  master  → live   (tadgeeg.com)"
    echo "  dev     → dev    (dev.tadgeeg.com)"
    echo "  test    → test   (test.tadgeeg.com)"
    echo ""
    ;;
esac
