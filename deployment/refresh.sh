#!/bin/bash
# ============================================================
# FinAI — Quick Refresh Script
# Usage: bash refresh.sh [live|dev|test]
#
# Performs a fast in-place refresh WITHOUT a full re-deployment:
#   1. Pull latest code from git
#   2. Install/update Python requirements
#   3. Run migrations
#   4. Collect static files
#   5. Copy static to web root
#   6. Restart application services
#   7. Test nginx config + reload nginx
#   8. Smoke-test the live URL
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV="${1:-live}"

ENV_FILE="$SCRIPT_DIR/config/${ENV}.env"
[ -f "$ENV_FILE" ] || { echo "❌ Unknown environment: $ENV  (live|dev|test)"; exit 1; }
source "$ENV_FILE"
SYNC_REPO_URL="${SYNC_REPO_URL:-$REPO_URL}"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/refresh.log"
LOCK_FILE="/var/lock/finai_refresh_${ENV}.lock"

exec 200>"$LOCK_FILE"
flock -n 200 || { echo "⏳ Another refresh is already running for [$ENV_LABEL]. Exiting."; exit 0; }

log() { echo "$(date '+%F %T') [$ENV_LABEL] $1" | tee -a "$LOG_FILE"; }

clean_untracked() {
  git clean -fd \
    -e ".secret.env" \
    -e "venv/" \
    -e ".venv/" >>"$LOG_FILE" 2>&1
}

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  FinAI [$ENV_LABEL] — QUICK REFRESH          ║"
echo "╚══════════════════════════════════════════════╝"
echo "  Environment : $ENV_LABEL"
echo "  Domain      : https://$DOMAIN_MAIN"
echo "  Path        : $BACKEND_DIR"
echo ""

START_TIME=$(date +%s)

# ── 1. Git pull ───────────────────────────────────────────────────────────────
log "🔄 [1/8] Syncing git ($BRANCH)..."
cd "$PROJECT_ROOT"
git remote set-url origin "$SYNC_REPO_URL" >>"$LOG_FILE" 2>&1
git fetch origin "$BRANCH" >>"$LOG_FILE" 2>&1
git reset --hard "origin/$BRANCH" >>"$LOG_FILE" 2>&1
clean_untracked
COMMIT=$(git log -1 --format="%h — %s (%ar)")
log "📌 HEAD: $COMMIT"

# ── 2. Requirements ───────────────────────────────────────────────────────────
log "📦 [2/8] Installing/updating Python requirements..."
"$VENV_DIR/bin/pip" install -q --upgrade pip >>"$LOG_FILE" 2>&1
[ -f "$BACKEND_DIR/requirements.txt" ] && \
  "$VENV_DIR/bin/pip" install -q -r "$BACKEND_DIR/requirements.txt" >>"$LOG_FILE" 2>&1
log "✅ Requirements up to date"

# ── 3. Migrations ─────────────────────────────────────────────────────────────
log "🗄️  [3/8] Running database migrations..."
cd "$BACKEND_DIR"
source "$VENV_DIR/bin/activate"
python manage.py migrate --noinput >>"$LOG_FILE" 2>&1
log "✅ Migrations complete"

# ── 4. Collect static ─────────────────────────────────────────────────────────
log "📦 [4/8] Collecting static files..."
python manage.py collectstatic --noinput --clear >>"$LOG_FILE" 2>&1
log "✅ Static collected"

# ── 5. Copy static to web root ────────────────────────────────────────────────
log "📁 [5/8] Copying static files to $STATIC_ROOT..."
mkdir -p "$STATIC_ROOT"
cp -r staticfiles/. "$STATIC_ROOT/" 2>/dev/null || true
chown -R www-data:www-data "$STATIC_ROOT"
chmod -R 755 "$STATIC_ROOT"
log "✅ Static files deployed"

# Also ensure media dir permissions
mkdir -p "$MEDIA_ROOT"
chown -R www-data:www-data "$MEDIA_ROOT"

# ── 6. Restart services ───────────────────────────────────────────────────────
log "🔄 [6/8] Restarting application services..."
for SVC in "$SERVICE_NAME" "${SERVICE_NAME}_celery" "${SERVICE_NAME}_celerybeat"; do
  if systemctl list-unit-files --type=service | grep -q "^${SVC}.service"; then
    systemctl restart "$SVC" >>"$LOG_FILE" 2>&1
    sleep 2
    systemctl is-active --quiet "$SVC" \
      && log "  ✅ $SVC restarted OK" \
      || log "  ❌ $SVC failed to start"
  fi
done

# ── 7. Nginx test + reload ────────────────────────────────────────────────────
log "🌐 [7/8] Testing and reloading Nginx..."
nano /etc/nginx/sites-available/"$NGINX_SITE_NAME" --view 2>/dev/null || true
nginx -t >>"$LOG_FILE" 2>&1 || { log "❌ Nginx config invalid!"; nginx -t; exit 1; }
systemctl reload nginx >>"$LOG_FILE" 2>&1
log "✅ Nginx reloaded"

# ── 8. Smoke test ─────────────────────────────────────────────────────────────
log "🔍 [8/8] Smoke-testing https://$DOMAIN_MAIN/health/ ..."
sleep 3
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 15 "https://$DOMAIN_MAIN/health/" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "301" || "$HTTP_CODE" == "302" ]]; then
  log "✅ Smoke test PASSED (HTTP $HTTP_CODE)"
else
  log "⚠️  Smoke test returned HTTP $HTTP_CODE (may still be starting up)"
fi

# ── Permissions final pass ────────────────────────────────────────────────────
chown -R www-data:www-data "$WEB_ROOT" 2>/dev/null || true
chmod -R 755 "$WEB_ROOT"

# ── Summary ───────────────────────────────────────────────────────────────────
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo ""
echo "══════════════════════════════════════════════════"
echo "  ✅ Refresh COMPLETE for [$ENV_LABEL]"
echo "  Commit  : $COMMIT"
echo "  Domain  : https://$DOMAIN_MAIN"
echo "  Duration: ${ELAPSED}s"
echo "══════════════════════════════════════════════════"
log "🎉 Refresh completed in ${ELAPSED}s"

# ── Static admin check ────────────────────────────────────────────────────────
echo ""
echo "Static admin check:"
ls -la "$STATIC_ROOT/admin" 2>/dev/null | head -5 || echo "  (admin static not found)"
