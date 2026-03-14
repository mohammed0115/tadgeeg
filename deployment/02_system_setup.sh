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

echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║  FinAI [$ENV_LABEL] — STEP 02: System Setup      ║"
echo "╚═══════════════════════════════════════════════════╝"
echo ""

# ── System update ─────────────────────────────────────────────────────────────
log "🔄 Updating apt package lists..."
apt-get update -y >>"$LOG_FILE" 2>&1

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
  libmysqlclient-dev
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
    apt-get install -y "$pkg" >>"$LOG_FILE" 2>&1
  fi
done

# ── Python 3.12 ───────────────────────────────────────────────────────────────
if command -v python3.12 &>/dev/null; then
  PY_VER=$(python3.12 --version 2>&1 | awk '{print $2}')
  log "✅ Python 3.12 already installed ($PY_VER)"
else
  log "🐍 Installing Python 3.12 from deadsnakes PPA..."
  add-apt-repository -y ppa:deadsnakes/ppa >>"$LOG_FILE" 2>&1
  apt-get update -y >>"$LOG_FILE" 2>&1
  apt-get install -y python3.12 python3.12-venv python3.12-dev python3.12-distutils >>"$LOG_FILE" 2>&1
  log "✅ Python 3.12 installed"
fi

# ── MySQL client ──────────────────────────────────────────────────────────────
if command -v mysql &>/dev/null; then
  log "✅ MySQL client already installed"
else
  log "🗄️  Installing MySQL client..."
  apt-get install -y mysql-client >>"$LOG_FILE" 2>&1
  log "✅ MySQL client installed"
fi

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
"$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel >>"$LOG_FILE" 2>&1

# ── Install Python requirements ────────────────────────────────────────────────
REQUIREMENTS="$BACKEND_DIR/requirements.txt"
if [ -f "$REQUIREMENTS" ]; then
  log "📦 Installing Python requirements..."
  "$VENV_DIR/bin/pip" install -r "$REQUIREMENTS" >>"$LOG_FILE" 2>&1
  log "✅ Requirements installed"
else
  log "⚠️  requirements.txt not found at $REQUIREMENTS (run Git sync first)"
fi

# ── Redis enable & start ──────────────────────────────────────────────────────
log "🔴 Enabling Redis..."
systemctl enable redis-server >>"$LOG_FILE" 2>&1
systemctl start redis-server >>"$LOG_FILE" 2>&1
systemctl is-active --quiet redis-server \
  && log "✅ Redis is running" \
  || log "❌ Redis failed to start"

echo ""
echo "✅ [STEP 02] System Setup COMPLETED for [$ENV_LABEL]"
