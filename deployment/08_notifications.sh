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
export DEBIAN_FRONTEND=noninteractive

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/notifications.log"
STATUS_FILE="$LOG_DIR/health.status"

log() { echo "$(date '+%F %T') [$ENV_LABEL] $1" | tee -a "$LOG_FILE"; }

APT_RETRY_COUNT="${APT_RETRY_COUNT:-3}"

run_with_retries() {
  local description="$1"
  shift
  local attempt=1

  until "$@" >>"$LOG_FILE" 2>&1; do
    if [ "$attempt" -ge "$APT_RETRY_COUNT" ]; then
      log "❌ ${description} failed after ${APT_RETRY_COUNT} attempts"
      return 1
    fi

    log "⚠️  ${description} failed (attempt ${attempt}/${APT_RETRY_COUNT}) — retrying in 5 seconds..."
    attempt=$((attempt + 1))
    sleep 5
  done

  return 0
}

apt_update() {
  run_with_retries "apt-get update" apt-get update -y
}

apt_install() {
  [ "$#" -gt 0 ] || return 0
  run_with_retries "apt-get install: $*" apt-get install -y "$@"
}

mail_available() {
  command -v mail &>/dev/null
}

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  FinAI [$ENV_LABEL] — STEP 08: Notifications Setup  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Install mail utilities ────────────────────────────────────────────────────
if mail_available; then
  log "✅ Mail utilities already installed"
else
  log "📦 Installing mail utilities..."
  apt_update || true

  if apt_install mailutils || apt_install bsd-mailx; then
    log "✅ Mail utilities installed"
  else
    log "⚠️  Could not install mail utilities — email alerts will fall back to log files only"
  fi
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
set -euo pipefail

ALERT_EMAIL="$ALERT_EMAIL"
ENV_LABEL="$ENV_LABEL"
STATUS_FILE="$STATUS_FILE"
LOG_DIR="$LOG_DIR"
SERVER_IP="$SERVER_IP"
DOMAIN_MAIN="$DOMAIN_MAIN"
HEALTH_LOG="$LOG_DIR/health.log"

send_alert() {
  local subject="\$1"
  local body="\$2"

  if [ -n "\$ALERT_EMAIL" ] && command -v mail &>/dev/null; then
    echo "\$body" | mail -s "[FinAI \$ENV_LABEL ALERT] \$subject" "\$ALERT_EMAIL" 2>/dev/null || true
  fi

  echo "\$(date '+%F %T') ALERT: \$subject" >> "\$LOG_DIR/alerts.log"
  echo "\$body" >> "\$LOG_DIR/alerts.log"
  echo "" >> "\$LOG_DIR/alerts.log"
}

case "\${1:-health}" in
  health)
    if [ -f "\$STATUS_FILE" ] && [ -s "\$STATUS_FILE" ]; then
      ISSUES=\$(cat "\$STATUS_FILE")
      BODY="FinAI [\$ENV_LABEL] health check detected issues at \$(date):

\$ISSUES

Server: \$SERVER_IP
Domain: https://\$DOMAIN_MAIN
Log:    \$HEALTH_LOG

-- FinAI Auto-Monitor"

      send_alert "Health Check Issues Detected" "\$BODY"
    fi
    ;;
  service-failure)
    UNIT_NAME="\${2:-unknown.service}"
    BODY="FinAI [\$ENV_LABEL] detected a service failure.

Service : \$UNIT_NAME
Server  : \$SERVER_IP
Domain  : https://\$DOMAIN_MAIN
Time    : \$(date)

Run: journalctl -u \$UNIT_NAME -n 80 --no-pager

-- FinAI Auto-Monitor"

    send_alert "Service Failure: \$UNIT_NAME" "\$BODY"
    ;;
  deployment-success)
    BODY="\${2:-FinAI deployment completed successfully.}"
    send_alert "Deployment Successful" "\$BODY"
    ;;
esac
SCRIPT

chmod +x "$ALERT_SCRIPT"
log "✅ Alert script created"

# ── Alert cron (runs after health check — every 5 min) ──────────────────────
ALERT_CRON_FILE="/etc/cron.d/finai_alert_${ENV}"
ALERT_CRON="*/5 * * * * root $ALERT_SCRIPT"

echo "$ALERT_CRON" > "$ALERT_CRON_FILE"
chmod 644 "$ALERT_CRON_FILE"
log "⏰ Alert cron installed/updated"

# ── Systemd on-failure email for critical services ────────────────────────────
for SVC in "$SERVICE_NAME" "${SERVICE_NAME}_celery" "${SERVICE_NAME}_celerybeat"; do
  SVC_FILE="/etc/systemd/system/${SVC}.service"
  if [ -f "$SVC_FILE" ]; then
    OVERRIDE_DIR="/etc/systemd/system/${SVC}.service.d"
    mkdir -p "$OVERRIDE_DIR"
    cat > "$OVERRIDE_DIR/alert.conf" <<OVERRIDE
[Unit]
OnFailure=finai-failure-alert@%n.service
OVERRIDE
    log "⚙️  OnFailure override installed for $SVC"
  fi
done

# ── Failure alert systemd unit ────────────────────────────────────────────────
FAILURE_UNIT="/etc/systemd/system/finai-failure-alert@.service"
cat > "$FAILURE_UNIT" <<UNIT
[Unit]
Description=FinAI Service Failure Alert for %i

[Service]
Type=oneshot
ExecStart=/bin/bash -lc '$ALERT_SCRIPT service-failure "%i"'
UNIT
systemctl daemon-reload >>"$LOG_FILE" 2>&1
log "✅ Failure alert systemd unit created/updated"

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
$(systemctl is-active "${SERVICE_NAME}_celerybeat" 2>/dev/null && echo "  ✅ Celery beat" || echo "  ❌ Celery beat")
$(systemctl is-active nginx 2>/dev/null && echo "  ✅ Nginx" || echo "  ❌ Nginx")
$(systemctl is-active redis-server 2>/dev/null && echo "  ✅ Redis" || echo "  ❌ Redis")

-- FinAI Auto-Deployment"

if [ -n "$ALERT_EMAIL" ] && mail_available; then
  "$ALERT_SCRIPT" deployment-success "$DEPLOY_MSG"
  log "📧 Deployment notification dispatched to $ALERT_EMAIL"
else
  log "⚠️  mail command not available or alert email empty — skipping email notification"
fi

# Always log the message
echo "$DEPLOY_MSG" >> "$LOG_DIR/deployments.log"
log "📋 Deployment logged to $LOG_DIR/deployments.log"

echo ""
echo "✅ [STEP 08] Notifications Setup COMPLETED for [$ENV_LABEL]"
echo "   Alert email: $ALERT_EMAIL"
