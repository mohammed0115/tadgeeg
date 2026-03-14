#!/bin/bash
# ============================================================
# FinAI Deployment — Step 02: System Setup
# Usage: bash 02_system_setup.sh [live|dev|test]
# Installs: Python 3.12, Nginx, MySQL client, Redis, build tools
# Smart: skips already-installed packages
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV="${1:-live}"

ENV_FILE="$SCRIPT_DIR/config/${ENV}.env"
[ -f "$ENV_FILE" ] || { echo "❌ Unknown environment: $ENV"; exit 1; }
source "$ENV_FILE"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/system_setup.log"

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

pip_install() {
  run_with_retries "pip install: $*" "$VENV_DIR/bin/pip" "$@"
}

require_command() {
  local command_name="$1"
  local hint="$2"

  command -v "$command_name" &>/dev/null || {
    log "❌ ${command_name} is still missing. ${hint}"
    exit 1
  }
}

echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║  FinAI [$ENV_LABEL] — STEP 02: System Setup      ║"
echo "╚═══════════════════════════════════════════════════╝"
echo ""

# ── System update ─────────────────────────────────────────────────────────────
log "🔄 Updating apt package lists..."
apt_update

# ── Core packages ─────────────────────────────────────────────────────────────
log "📦 Installing core system packages..."
PKGS=(
  software-properties-common
  build-essential
  git
  curl
  wget
  unzip
  nginx
  ca-certificates
  default-libmysqlclient-dev
  libmariadb-dev-compat
  pkg-config
  libffi-dev
  libssl-dev
  libjpeg-dev
  libpng-dev
  libfreetype6-dev
  zlib1g-dev
  redis-server
  supervisor
  logrotate
  bc
)

for pkg in "${PKGS[@]}"; do
  if dpkg -s "$pkg" &>/dev/null; then
    log "  ✅ Already installed: $pkg"
  else
    log "  📥 Installing: $pkg"
    apt_install "$pkg"
  fi
done

require_command nginx "Nginx should have been installed during core package setup."

# ── Python 3.12 ───────────────────────────────────────────────────────────────
if command -v python3.12 &>/dev/null; then
  PY_VER=$(python3.12 --version 2>&1 | awk '{print $2}')
  log "✅ Python 3.12 already installed ($PY_VER)"
else
  log "🐍 Installing Python 3.12 from deadsnakes PPA..."
  run_with_retries "add-apt-repository deadsnakes" add-apt-repository -y ppa:deadsnakes/ppa
  apt_update
  apt_install python3.12 python3.12-venv python3.12-dev python3.12-distutils
  log "✅ Python 3.12 installed"
fi

require_command python3.12 "Python 3.12 is required for the FinAI backend."

# ── MySQL client ──────────────────────────────────────────────────────────────
if command -v mysql &>/dev/null; then
  log "✅ MySQL client already installed"
else
  log "🗄️  Installing MySQL client..."
  if ! apt_install mysql-client; then
    log "⚠️  mysql-client package unavailable — trying default-mysql-client"
    apt_install default-mysql-client
  fi
  log "✅ MySQL client installed"
fi

require_command mysql "Install either mysql-client or default-mysql-client."

# ── Directory structure ────────────────────────────────────────────────────────
log "📁 Creating web root directories..."
for DIR in "$WEB_ROOT" "$WEB_ROOT/app" "$STATIC_ROOT" "$MEDIA_ROOT" "$LOG_DIR"; do
  if [ -d "$DIR" ]; then
    log "  ✅ Exists: $DIR"
  else
    mkdir -p "$DIR"
    log "  📁 Created: $DIR"
  fi
done

chown -R www-data:www-data "$WEB_ROOT" 2>/dev/null || true
chmod -R 755 "$WEB_ROOT"

# ── Virtual environment ────────────────────────────────────────────────────────
mkdir -p "$BACKEND_DIR"

if [ -d "$VENV_DIR" ]; then
  log "✅ Virtual environment already exists at $VENV_DIR"
else
  log "🐍 Creating virtual environment..."
  python3.12 -m venv "$VENV_DIR"
  log "✅ Virtual environment created"
fi

log "📦 Upgrading pip, setuptools, wheel..."
pip_install install --upgrade pip setuptools wheel

# ── Install Python requirements ────────────────────────────────────────────────
REQUIREMENTS="$BACKEND_DIR/requirements.txt"
if [ -f "$REQUIREMENTS" ]; then
  log "📦 Installing Python requirements..."
  pip_install install -r "$REQUIREMENTS"
  log "✅ Requirements installed"

  log "🔎 Verifying Python runtime packages..."
  "$VENV_DIR/bin/python" -c "import django, celery, gunicorn, MySQLdb" >>"$LOG_FILE" 2>&1
  log "✅ Python runtime packages verified"
else
  log "⚠️  requirements.txt not found at $REQUIREMENTS (run Git sync first)"
fi

# ── Redis enable & start ──────────────────────────────────────────────────────
log "🔴 Enabling Redis..."
systemctl enable redis-server >>"$LOG_FILE" 2>&1
systemctl start redis-server >>"$LOG_FILE" 2>&1
systemctl is-active --quiet redis-server \
  && log "✅ Redis is running" \
  || {
    log "❌ Redis failed to start"
    journalctl -u redis-server -n 50 --no-pager >>"$LOG_FILE" 2>&1 || true
  }

log "🌐 Ensuring Nginx is enabled..."
systemctl enable nginx >>"$LOG_FILE" 2>&1 || true
systemctl start nginx >>"$LOG_FILE" 2>&1 || log "⚠️  Nginx did not start yet — Step 05 will rebuild its config"

echo ""
echo "✅ [STEP 02] System Setup COMPLETED for [$ENV_LABEL]"
