#!/bin/bash
# ============================================================
# FinAI Deployment — Step 04: Gunicorn Systemd Service
# Usage: bash 04_gunicorn_service.sh [live|dev|test]
# Smart: updates service file if exists, creates if not
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV="${1:-live}"

ENV_FILE="$SCRIPT_DIR/config/${ENV}.env"
[ -f "$ENV_FILE" ] || { echo "❌ Unknown environment: $ENV"; exit 1; }
source "$ENV_FILE"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/gunicorn_setup.log"

log() { echo "$(date '+%F %T') [$ENV_LABEL] $1" | tee -a "$LOG_FILE"; }

resolve_socket_path() {
  local configured_socket="$1"
  local configured_dir
  configured_dir="$(dirname "$configured_socket")"

  if [ "$configured_dir" = "/run" ]; then
    echo "/run/${SERVICE_NAME}/$(basename "$configured_socket")"
  else
    echo "$configured_socket"
  fi
}

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
CELERY_SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}_celery.service"
CELERYBEAT_FILE="/etc/systemd/system/${SERVICE_NAME}_celerybeat.service"
SYSTEMD_SOCKET="$(resolve_socket_path "$SOCKET")"
SYSTEMD_SOCKET_DIR="$(dirname "$SYSTEMD_SOCKET")"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  FinAI [$ENV_LABEL] — STEP 04: Gunicorn Service     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Pre-flight checks ─────────────────────────────────────────────────────────
[ -d "$VENV_DIR" ] || { log "❌ venv not found: $VENV_DIR"; exit 1; }
[ -f "$BACKEND_DIR/manage.py" ] || { log "❌ manage.py not found: $BACKEND_DIR"; exit 1; }
chown -R www-data:www-data "$LOG_DIR"
chmod 755 "$LOG_DIR"

# ── Load secrets ──────────────────────────────────────────────────────────────
SECRET_FILE="$WEB_ROOT/.secret.env"
SECRET_ENV_BLOCK=""
if [ -f "$SECRET_FILE" ]; then
  while IFS= read -r line; do
    [[ "$line" =~ ^[A-Z_]+=.+ ]] && SECRET_ENV_BLOCK="${SECRET_ENV_BLOCK}Environment=\"$line\"\n" || true
  done < "$SECRET_FILE"
fi

load_secret_env() {
  [ -f "$SECRET_FILE" ] || return 0

  while IFS= read -r line; do
    [[ "$line" =~ ^[A-Z_]+=.+ ]] || continue
    export "$line"
  done < "$SECRET_FILE"
}

ensure_runtime_dependencies() {
  log "🔎 Verifying Django runtime dependencies..."

  if python -c "import os, django, celery, gunicorn; __import__('MySQLdb') if (os.environ.get('DB_ENGINE') == 'django.db.backends.mysql' or os.environ.get('DB_NAME')) else None" >>"$LOG_FILE" 2>&1; then
    log "✅ Django runtime dependencies verified"
    return 0
  fi

  log "⚠️  Runtime dependency check failed — retrying pip install from requirements.txt"
  if [ ! -f "$BACKEND_DIR/requirements.txt" ]; then
    log "❌ requirements.txt not found at $BACKEND_DIR/requirements.txt"
    exit 1
  fi

  pip install --upgrade pip setuptools wheel >>"$LOG_FILE" 2>&1
  pip install -r "$BACKEND_DIR/requirements.txt" >>"$LOG_FILE" 2>&1

  python -c "import os, django, celery, gunicorn; __import__('MySQLdb') if (os.environ.get('DB_ENGINE') == 'django.db.backends.mysql' or os.environ.get('DB_NAME')) else None" >>"$LOG_FILE" 2>&1 || {
    log "❌ Runtime dependencies are still missing after reinstall"
    exit 1
  }

  log "✅ Django runtime dependencies verified"
}

# ── Django prep ───────────────────────────────────────────────────────────────
log "🔄 Activating venv and running Django management commands..."
cd "$BACKEND_DIR"
source "$VENV_DIR/bin/activate"
load_secret_env

ensure_runtime_dependencies

log "🗄️  Running database migrations..."
python manage.py migrate --noinput >>"$LOG_FILE" 2>&1
log "✅ Migrations done"

log "📦 Collecting static files..."
python manage.py collectstatic --noinput >>"$LOG_FILE" 2>&1

log "📁 Copying static files to $STATIC_ROOT..."
mkdir -p "$STATIC_ROOT"
cp -r staticfiles/. "$STATIC_ROOT/" 2>/dev/null || true
chown -R www-data:www-data "$STATIC_ROOT"
chmod -R 755 "$STATIC_ROOT"
log "✅ Static files collected"

# ── Write Gunicorn systemd service ────────────────────────────────────────────
log "⚙️  Writing systemd service: $SERVICE_FILE"

cat > "$SERVICE_FILE" <<UNIT
[Unit]
Description=FinAI [$ENV_LABEL] — Gunicorn Application Server
After=network.target mysql.service redis.service
Wants=redis.service

[Service]
Type=notify
NotifyAccess=all
PermissionsStartOnly=true
User=www-data
Group=www-data
WorkingDirectory=$BACKEND_DIR
RuntimeDirectory=${SERVICE_NAME}
RuntimeDirectoryMode=0755

# Core environment
Environment="DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE}"
Environment="DJANGO_ENV=${DJANGO_ENV}"
Environment="ALLOWED_HOSTS=${ALLOWED_HOSTS}"
Environment="TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata"
Environment="REDIS_URL=${REDIS_URL}"
Environment="DB_NAME=${DB_NAME}"
Environment="DB_USER=${DB_USER}"
Environment="DB_HOST=${DB_HOST}"
Environment="DB_PORT=${DB_PORT}"
$(printf "%b" "$SECRET_ENV_BLOCK")

# Socket cleanup on start
ExecStartPre=/usr/bin/install -d -o www-data -g www-data -m 0755 ${SYSTEMD_SOCKET_DIR}
ExecStartPre=/bin/rm -f ${SYSTEMD_SOCKET}

# Gunicorn
ExecStart=${VENV_DIR}/bin/gunicorn ${DJANGO_SETTINGS_MODULE%.*}.wsgi:application \\
  --name finai_${ENV} \\
  --workers ${GUNICORN_WORKERS} \\
  --bind unix:${SYSTEMD_SOCKET} \\
  --timeout ${GUNICORN_TIMEOUT} \\
  --max-requests ${GUNICORN_MAX_REQUESTS} \\
  --max-requests-jitter 50 \\
  --log-level info \\
  --access-logfile ${LOG_DIR}/access.log \\
  --error-logfile ${LOG_DIR}/error.log \\
  --capture-output \\
  --forwarded-allow-ips='*'

ExecReload=/bin/kill -s HUP \$MAINPID

Restart=on-failure
RestartSec=5
KillMode=mixed
TimeoutStopSec=30

# Security hardening
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
UNIT

# ── Write Celery worker service ───────────────────────────────────────────────
log "⚙️  Writing Celery worker service: $CELERY_SERVICE_FILE"

cat > "$CELERY_SERVICE_FILE" <<UNIT
[Unit]
Description=FinAI [$ENV_LABEL] — Celery Worker
After=network.target redis.service mysql.service
Requires=redis.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=$BACKEND_DIR

Environment="DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE}"
Environment="DJANGO_ENV=${DJANGO_ENV}"
Environment="REDIS_URL=${REDIS_URL}"
Environment="DB_NAME=${DB_NAME}"
Environment="DB_USER=${DB_USER}"
Environment="DB_HOST=${DB_HOST}"
Environment="DB_PORT=${DB_PORT}"
$(printf "%b" "$SECRET_ENV_BLOCK")

ExecStart=${VENV_DIR}/bin/celery -A finai_backend worker \\
  --loglevel=info \\
  --logfile=${LOG_DIR}/celery.log \\
  --concurrency=4

ExecStop=/bin/kill -s TERM \$MAINPID

Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

# ── Write Celery beat service ─────────────────────────────────────────────────
log "⚙️  Writing Celery beat service: $CELERYBEAT_FILE"

cat > "$CELERYBEAT_FILE" <<UNIT
[Unit]
Description=FinAI [$ENV_LABEL] — Celery Beat Scheduler
After=network.target redis.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=$BACKEND_DIR

Environment="DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE}"
Environment="DJANGO_ENV=${DJANGO_ENV}"
Environment="REDIS_URL=${REDIS_URL}"
$(printf "%b" "$SECRET_ENV_BLOCK")

ExecStart=${VENV_DIR}/bin/celery -A finai_backend beat \\
  --loglevel=info \\
  --logfile=${LOG_DIR}/celerybeat.log \\
  --schedule ${LOG_DIR}/celerybeat-schedule

Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

# ── Socket file permissions ───────────────────────────────────────────────────


# ── Systemd reload & enable ───────────────────────────────────────────────────
log "🔄 Reloading systemd..."
systemctl daemon-reload

for SVC in "$SERVICE_NAME" "${SERVICE_NAME}_celery" "${SERVICE_NAME}_celerybeat"; do
  log "▶️  Enabling & (re)starting: $SVC"
  systemctl enable "$SVC" >>"$LOG_FILE" 2>&1
  if ! systemctl restart "$SVC" >>"$LOG_FILE" 2>&1; then
    log "❌ Failed to restart $SVC"
    systemctl status "$SVC" --no-pager >>"$LOG_FILE" 2>&1 || true
    journalctl -u "$SVC" -n 50 --no-pager >>"$LOG_FILE" 2>&1 || true
    exit 1
  fi
done

sleep 4

# ── Status check ──────────────────────────────────────────────────────────────
FAILED=0
for SVC in "$SERVICE_NAME" "${SERVICE_NAME}_celery" "${SERVICE_NAME}_celerybeat"; do
  if systemctl is-active --quiet "$SVC"; then
    log "✅ $SVC is running"
  else
    log "❌ $SVC FAILED to start"
    journalctl -u "$SVC" -n 20 --no-pager >> "$LOG_FILE" 2>&1
    FAILED=$((FAILED+1))
  fi
done

[ "$FAILED" -eq 0 ] || exit 1

echo ""
echo "✅ [STEP 04] Gunicorn & Celery Services SETUP COMPLETED for [$ENV_LABEL]"
