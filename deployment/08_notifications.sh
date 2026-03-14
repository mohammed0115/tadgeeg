#!/bin/bash
# ============================================================
# FinAI Deployment — Step 08: Notifications & Alerts
# Usage: bash 08_notifications.sh [live|dev|test]
# Sets up: email alerts on service failure, deployment summary
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV="${1:-live}"

ENV_FILE="$SCRIPT_DIR/config/${ENV}.env"
[ -f "$ENV_FILE" ] || { echo "❌ Unknown environment: $ENV"; exit 1; }
source "$ENV_FILE"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/notifications.log"

log() { echo "$(date '+%F %T') [$ENV_LABEL] $1" | tee -a "$LOG_FILE"; }

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  FinAI [$ENV_LABEL] — STEP 08: Notifications Setup  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Install mail utilities ────────────────────────────────────────────────────
if command -v mail &>/dev/null || command -v sendmail &>/dev/null; then
  log "✅ Mail utilities already installed"
else
  log "📦 Installing mail utilities..."
  apt-get install -y mailutils ssmtp >>"$LOG_FILE" 2>&1 || \
  apt-get install -y postfix >>"$LOG_FILE" 2>&1 || \
  log "⚠️  Could not install mail utilities — email alerts disabled"
fi

# ── Load alert config from secret file ───────────────────────────────────────
SECRET_FILE="$WEB_ROOT/.secret.env"
ALERT_EMAIL="${ALERT_EMAIL:-$SSL_EMAIL}"
if [ -f "$SECRET_FILE" ] && grep -q "ALERT_EMAIL" "$SECRET_FILE"; then
  ALERT_EMAIL=$(grep "^ALERT_EMAIL=" "$SECRET_FILE" | cut -d= -f2)
fi

# ── Alert script ─────────────────────────────────────────────────────────────
ALERT_SCRIPT="/usr/local/bin/finai_alert_${ENV}.sh"
log "📝 Writing alert script: $ALERT_SCRIPT"

cat > "$ALERT_SCRIPT" <<SCRIPT
#!/bin/bash
# FinAI [$ENV_LABEL] — Service Alert Script
ALERT_EMAIL="$ALERT_EMAIL"
ENV_LABEL="$ENV_LABEL"
STATUS_FILE="$STATUS_FILE"
LOG_DIR="$LOG_DIR"

send_alert() {
  local subject="\$1"
  local body="\$2"
  if command -v mail &>/dev/null; then
    echo "\$body" | mail -s "[FinAI \$ENV_LABEL ALERT] \$subject" "\$ALERT_EMAIL" 2>/dev/null || true
  fi
  # Also log to file
  echo "\$(date '+%F %T') ALERT: \$subject" >> "\$LOG_DIR/alerts.log"
  echo "\$body" >> "\$LOG_DIR/alerts.log"
}

# Read status file for issues
if [ -f "\$STATUS_FILE" ] && [ -s "\$STATUS_FILE" ]; then
  ISSUES=\$(cat "\$STATUS_FILE")
  BODY="FinAI [\$ENV_LABEL] health check detected issues at \$(date):

\$ISSUES

Server: $SERVER_IP
Domain: https://$DOMAIN_MAIN
Log:    $LOG_DIR/health.log

-- FinAI Auto-Monitor"

  send_alert "Health Check Issues Detected" "\$BODY"
fi
SCRIPT

chmod +x "$ALERT_SCRIPT"
log "✅ Alert script created"

# ── Alert cron (runs after health check — every 5 min) ──────────────────────
ALERT_CRON_FILE="/etc/cron.d/finai_alert_${ENV}"
ALERT_CRON="*/5 * * * * root $ALERT_SCRIPT"

if [ -f "$ALERT_CRON_FILE" ]; then
  echo "$ALERT_CRON" > "$ALERT_CRON_FILE"
  log "✅ Alert cron updated"
else
  echo "$ALERT_CRON" > "$ALERT_CRON_FILE"
  chmod 644 "$ALERT_CRON_FILE"
  log "⏰ Alert cron installed"
fi

# ── Systemd on-failure email for critical services ────────────────────────────
for SVC in "$SERVICE_NAME" "${SERVICE_NAME}_celery"; do
  SVC_FILE="/etc/systemd/system/${SVC}.service"
  if [ -f "$SVC_FILE" ] && ! grep -q "OnFailure" "$SVC_FILE"; then
    # Create override drop-in for failure notification
    OVERRIDE_DIR="/etc/systemd/system/${SVC}.service.d"
    mkdir -p "$OVERRIDE_DIR"
    cat > "$OVERRIDE_DIR/alert.conf" <<OVERRIDE
[Unit]
OnFailure=finai-failure-alert@%n.service
OVERRIDE
    log "⚙️  OnFailure override added for $SVC"
  fi
done

# ── Failure alert systemd unit ────────────────────────────────────────────────
FAILURE_UNIT="/etc/systemd/system/finai-failure-alert@.service"
if [ ! -f "$FAILURE_UNIT" ]; then
  cat > "$FAILURE_UNIT" <<UNIT
[Unit]
Description=FinAI Service Failure Alert for %i

[Service]
Type=oneshot
ExecStart=/bin/bash -c '\
  echo "FinAI service %i failed on $SERVER_IP ($ENV_LABEL) at \$(date). Check: journalctl -u %i -n 50" \
  | mail -s "[FinAI $ENV_LABEL CRITICAL] Service %i FAILED" $ALERT_EMAIL 2>/dev/null || true'
UNIT
  systemctl daemon-reload >>"$LOG_FILE" 2>&1
  log "✅ Failure alert systemd unit created"
fi

# ── Send deployment success notification ──────────────────────────────────────
COMMIT=$(git -C "$PROJECT_ROOT" log -1 --format="%h — %s" 2>/dev/null || echo "N/A")

DEPLOY_MSG="FinAI [$ENV_LABEL] deployment completed successfully.

Environment : $ENV_LABEL
Domain      : https://$DOMAIN_MAIN
Server      : $SERVER_IP
Branch      : $BRANCH
Commit      : $COMMIT
Deployed at : $(date '+%F %T')

Services running:
$(systemctl is-active "$SERVICE_NAME" 2>/dev/null && echo "  ✅ Gunicorn ($SERVICE_NAME)" || echo "  ❌ Gunicorn ($SERVICE_NAME)")
$(systemctl is-active "${SERVICE_NAME}_celery" 2>/dev/null && echo "  ✅ Celery" || echo "  ❌ Celery")
$(systemctl is-active nginx 2>/dev/null && echo "  ✅ Nginx" || echo "  ❌ Nginx")
$(systemctl is-active redis-server 2>/dev/null && echo "  ✅ Redis" || echo "  ❌ Redis")

-- FinAI Auto-Deployment"

if command -v mail &>/dev/null; then
  echo "$DEPLOY_MSG" | mail -s "[FinAI $ENV_LABEL] Deployment Successful" "$ALERT_EMAIL" 2>/dev/null \
    && log "📧 Deployment notification sent to $ALERT_EMAIL" \
    || log "⚠️  Could not send email (mail not configured)"
else
  log "⚠️  mail command not available — skipping email notification"
fi

# Always log the message
echo "$DEPLOY_MSG" >> "$LOG_DIR/deployments.log"
log "📋 Deployment logged to $LOG_DIR/deployments.log"

echo ""
echo "✅ [STEP 08] Notifications Setup COMPLETED for [$ENV_LABEL]"
echo "   Alert email: $ALERT_EMAIL"
