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
export DEBIAN_FRONTEND=noninteractive

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/refresh.log"
LOCK_FILE="/var/lock/finai_refresh_${ENV}.lock"

exec 200>"$LOCK_FILE"
flock -n 200 || { echo "⏳ Another refresh is already running for [$ENV_LABEL]. Exiting."; exit 0; }

log() { echo "$(date '+%F %T') [$ENV_LABEL] $1" | tee -a "$LOG_FILE"; }

SECRET_FILE="$WEB_ROOT/.secret.env"
APT_RETRY_COUNT="${APT_RETRY_COUNT:-3}"
DJANGO_APP_LOG_DIR_DEFAULT="$LOG_DIR/django"

load_secret_env() {
  [ -f "$SECRET_FILE" ] || return 0

  while IFS= read -r line; do
    [[ "$line" =~ ^[A-Z_]+=.+ ]] || continue
    export "$line"
  done < "$SECRET_FILE"
}

clean_untracked() {
  git clean -fd \
    -e ".secret.env" \
    -e "venv/" \
    -e ".venv/" >>"$LOG_FILE" 2>&1
}

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

pip_install() {
  local original_path="$PATH"
  PATH="$VENV_DIR/bin:$PATH"
  run_with_retries "pip install: $*" "$VENV_DIR/bin/python" -m pip "$@"
  local status=$?
  PATH="$original_path"
  return $status
}

ensure_virtualenv() {
  if [ -d "$VENV_DIR" ] && [ ! -x "$VENV_DIR/bin/python" ]; then
    log "⚠️  Virtual environment at $VENV_DIR is incomplete — recreating it"
    rm -rf "$VENV_DIR"
  fi

  if [ ! -d "$VENV_DIR" ]; then
    command -v python3.12 &>/dev/null || {
      log "❌ python3.12 is required before refresh can recreate the virtual environment"
      exit 1
    }

    log "🐍 Recreating missing virtual environment..."
    python3.12 -m venv "$VENV_DIR"
  fi

  if [ ! -x "$VENV_DIR/bin/pip" ]; then
    log "🔧 Bootstrapping pip in the virtual environment..."
    "$VENV_DIR/bin/python" -m ensurepip --upgrade >>"$LOG_FILE" 2>&1
  fi

  export PATH="$VENV_DIR/bin:$PATH"
  hash -r
}

fix_web_root_permissions() {
  [ -d "$WEB_ROOT" ] || return 0

  if [ -d "$STATIC_ROOT" ]; then
    chown -R www-data:www-data "$STATIC_ROOT" 2>/dev/null || true
    find "$STATIC_ROOT" -type d -exec chmod 755 {} + 2>/dev/null || true
    find "$STATIC_ROOT" -type f -exec chmod 644 {} + 2>/dev/null || true
  fi

  if [ -d "$MEDIA_ROOT" ]; then
    chown -R www-data:www-data "$MEDIA_ROOT" 2>/dev/null || true
    find "$MEDIA_ROOT" -type d -exec chmod 755 {} + 2>/dev/null || true
    find "$MEDIA_ROOT" -type f -exec chmod 644 {} + 2>/dev/null || true
  fi

  if [ -f "$SECRET_FILE" ]; then
    chmod 600 "$SECRET_FILE" 2>/dev/null || true
  fi
}

prepare_django_log_dir() {
  DJANGO_APP_LOG_DIR="${DJANGO_LOG_DIR:-$DJANGO_APP_LOG_DIR_DEFAULT}"

  mkdir -p "$DJANGO_APP_LOG_DIR"
  touch "$DJANGO_APP_LOG_DIR/finai.log"

  chown -R www-data:www-data "$DJANGO_APP_LOG_DIR" 2>/dev/null || true
  chmod 755 "$DJANGO_APP_LOG_DIR" 2>/dev/null || true
  chmod 664 "$DJANGO_APP_LOG_DIR/finai.log" 2>/dev/null || true

  if [ -d "$BACKEND_DIR/logs" ]; then
    chown -R www-data:www-data "$BACKEND_DIR/logs" 2>/dev/null || true
  fi

  export DJANGO_LOG_DIR="$DJANGO_APP_LOG_DIR"
  log "✅ Django app log directory ready at $DJANGO_APP_LOG_DIR"
}

restart_service() {
  local service_name="$1"

  if ! systemctl list-unit-files --type=service | grep -q "^${service_name}.service"; then
    log "ℹ️  Skipping missing service: $service_name"
    return 0
  fi

  systemctl reset-failed "$service_name" >>"$LOG_FILE" 2>&1 || true

  if ! systemctl restart "$service_name" >>"$LOG_FILE" 2>&1; then
    log "❌ $service_name failed to restart"
    systemctl status "$service_name" --no-pager >>"$LOG_FILE" 2>&1 || true
    journalctl -u "$service_name" -n 80 --no-pager >>"$LOG_FILE" 2>&1 || true
    return 1
  fi

  sleep 2

  if ! systemctl is-active --quiet "$service_name"; then
    log "❌ $service_name is not active after restart"
    systemctl status "$service_name" --no-pager >>"$LOG_FILE" 2>&1 || true
    journalctl -u "$service_name" -n 80 --no-pager >>"$LOG_FILE" 2>&1 || true
    return 1
  fi

  log "  ✅ $service_name restarted OK"
}

ensure_nginx_ready() {
  if command -v nginx &>/dev/null; then
    return 0
  fi

  log "⚠️  Nginx is not installed — invoking deployment/05_nginx_setup.sh"
  bash "$SCRIPT_DIR/05_nginx_setup.sh" "$ENV" >>"$LOG_FILE" 2>&1
}

smoke_test_http() {
  if command -v curl &>/dev/null; then
    curl -sS -o /dev/null -w "%{http_code}" --max-time 15 -H "Host: $DOMAIN_MAIN" http://127.0.0.1/health/ 2>/dev/null || echo "000"
    return
  fi

  if command -v wget &>/dev/null; then
    wget -q -S --spider --timeout=15 --header="Host: $DOMAIN_MAIN" http://127.0.0.1/health/ 2>&1 | awk '/HTTP\// { code=$2 } END { print code ? code : "000" }' || echo "000"
    return
  fi

  echo "000"
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
ensure_virtualenv
pip_install install --upgrade pip setuptools wheel

if [ -f "$BACKEND_DIR/requirements.txt" ]; then
  if ! pip_install install -r "$BACKEND_DIR/requirements.txt"; then
    log "❌ Requirements installation failed — recent pip output:"
    tail -n 40 "$LOG_FILE" || true
    exit 1
  fi
else
  log "❌ requirements.txt not found at $BACKEND_DIR/requirements.txt"
  exit 1
fi

log "✅ Requirements up to date"

# ── 3. Migrations ─────────────────────────────────────────────────────────────
log "🗄️  [3/8] Running database migrations..."
cd "$BACKEND_DIR"
source "$VENV_DIR/bin/activate"
load_secret_env
prepare_django_log_dir
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
fix_web_root_permissions
log "✅ Static files deployed"

# Also ensure media dir permissions
mkdir -p "$MEDIA_ROOT"
fix_web_root_permissions

# ── 6. Restart services ───────────────────────────────────────────────────────
log "🔄 [6/8] Restarting application services..."
FAILED_SERVICES=0
for SVC in "$SERVICE_NAME" "${SERVICE_NAME}_celery" "${SERVICE_NAME}_celerybeat"; do
  restart_service "$SVC" || FAILED_SERVICES=$((FAILED_SERVICES + 1))
done

[ "$FAILED_SERVICES" -eq 0 ] || exit 1

# ── 7. Nginx test + reload ────────────────────────────────────────────────────
log "🌐 [7/8] Testing and reloading Nginx..."
ensure_nginx_ready
nginx -t >>"$LOG_FILE" 2>&1 || { log "❌ Nginx config invalid!"; nginx -t; exit 1; }
systemctl reload nginx >>"$LOG_FILE" 2>&1
log "✅ Nginx reloaded"

# ── 8. Smoke test ─────────────────────────────────────────────────────────────
log "🔍 [8/8] Smoke-testing local Nginx health endpoint for $DOMAIN_MAIN ..."
sleep 3
HTTP_CODE=$(smoke_test_http)
if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "301" || "$HTTP_CODE" == "302" || "$HTTP_CODE" == "307" || "$HTTP_CODE" == "308" ]]; then
  log "✅ Smoke test PASSED (HTTP $HTTP_CODE)"
else
  log "❌ Smoke test returned HTTP $HTTP_CODE"
  exit 1
fi

# ── Permissions final pass ────────────────────────────────────────────────────
fix_web_root_permissions

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
