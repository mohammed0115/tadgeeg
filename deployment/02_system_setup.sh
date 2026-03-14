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
export DEBIAN_FRONTEND=noninteractive

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

package_installed() {
  dpkg -s "$1" &>/dev/null
}

pip_install() {
  local original_path="$PATH"
  PATH="$VENV_DIR/bin:$PATH"
  run_with_retries "pip install: $*" "$VENV_DIR/bin/python" -m pip "$@"
  local status=$?
  PATH="$original_path"
  return $status
}

require_command() {
  local command_name="$1"
  local hint="$2"

  command -v "$command_name" &>/dev/null || {
    log "❌ ${command_name} is still missing. ${hint}"
    exit 1
  }
}

fix_web_root_permissions() {
  [ -d "$WEB_ROOT" ] || return 0

  find "$WEB_ROOT" -maxdepth 1 -type d -exec chmod 755 {} + 2>/dev/null || true

  if [ -d "$STATIC_ROOT" ]; then
    find "$STATIC_ROOT" -type d -exec chmod 755 {} + 2>/dev/null || true
    find "$STATIC_ROOT" -type f -exec chmod 644 {} + 2>/dev/null || true
  fi

  if [ -d "$MEDIA_ROOT" ]; then
    chown -R www-data:www-data "$MEDIA_ROOT" 2>/dev/null || true
    find "$MEDIA_ROOT" -type d -exec chmod 755 {} + 2>/dev/null || true
    find "$MEDIA_ROOT" -type f -exec chmod 644 {} + 2>/dev/null || true
  fi

  if [ -f "$WEB_ROOT/.secret.env" ]; then
    chmod 600 "$WEB_ROOT/.secret.env" 2>/dev/null || true
  fi
}

ensure_virtualenv() {
  if [ -d "$VENV_DIR" ] && [ ! -x "$VENV_DIR/bin/python" ]; then
    log "⚠️  Virtual environment at $VENV_DIR is incomplete — recreating it"
    rm -rf "$VENV_DIR"
  fi

  if [ -d "$VENV_DIR" ]; then
    log "✅ Virtual environment already exists at $VENV_DIR"
  else
    log "🐍 Creating virtual environment..."
    python3.12 -m venv "$VENV_DIR"
    log "✅ Virtual environment created"
  fi

  if [ ! -x "$VENV_DIR/bin/pip" ]; then
    log "🔧 Bootstrapping pip inside the virtual environment..."
    "$VENV_DIR/bin/python" -m ensurepip --upgrade >>"$LOG_FILE" 2>&1
  fi

  [ -x "$VENV_DIR/bin/python" ] || {
    log "❌ Virtual environment python executable is missing after setup"
    exit 1
  }
}

ensure_mysql_build_deps() {
  if command -v mariadb_config &>/dev/null || pkg-config --exists mariadb 2>/dev/null || [ -f /usr/include/mariadb/mysql.h ]; then
    log "✅ Existing MariaDB/MySQL development headers detected"
    return 0
  fi

  if package_installed default-libmysqlclient-dev || package_installed libmysqlclient-dev; then
    log "✅ MySQL build headers already installed"
    return 0
  fi

  if package_installed libmariadb-dev || package_installed libmariadb-dev-compat; then
    log "✅ MariaDB compatibility build headers already installed"
    return 0
  fi

  log "🧩 Installing MySQL/MariaDB build headers for mysqlclient..."

  if apt_install default-libmysqlclient-dev; then
    log "✅ Installed default-libmysqlclient-dev"
    return 0
  fi

  log "⚠️  default-libmysqlclient-dev unavailable — trying libmysqlclient-dev"
  if apt_install libmysqlclient-dev; then
    log "✅ Installed libmysqlclient-dev"
    return 0
  fi

  log "⚠️  libmysqlclient-dev unavailable — trying MariaDB compatibility headers"
  if apt_install libmariadb-dev libmariadb-dev-compat; then
    log "✅ Installed libmariadb-dev and libmariadb-dev-compat"
    return 0
  fi

  log "⚠️  libmariadb-dev package pair unavailable — trying libmariadb-dev-compat only"
  if apt_install libmariadb-dev-compat; then
    log "✅ Installed libmariadb-dev-compat"
    return 0
  fi

  log "❌ Could not install any MySQL/MariaDB development headers needed for mysqlclient"
  return 1
}

python_include_file() {
  python3.12 - <<'PY'
import sysconfig
from pathlib import Path

include_dir = sysconfig.get_paths().get("include", "")
print(Path(include_dir) / "Python.h")
PY
}

ensure_python_build_deps() {
  local include_file

  log "🧩 Ensuring Python 3.12 support packages (venv, distutils, headers)..."

  apt_install python3.12-venv || {
    log "❌ Failed to install python3.12-venv"
    return 1
  }

  if ! apt_install python3.12-distutils; then
    log "⚠️  python3.12-distutils unavailable — continuing without it"
  fi

  if ! apt_install python3.12-dev; then
    log "⚠️  python3.12-dev unavailable — trying libpython3.12-dev"
    if ! apt_install libpython3.12-dev; then
      log "⚠️  libpython3.12-dev unavailable — trying python3-dev"
      apt_install python3-dev || {
        log "❌ Could not install Python development headers"
        return 1
      }
    fi
  fi

  include_file="$(python_include_file 2>>"$LOG_FILE" || true)"

  if [ -z "$include_file" ] || [ ! -f "$include_file" ]; then
    log "❌ Python development header not found after installation: ${include_file:-unknown}"
    return 1
  fi

  log "✅ Python development headers available at $include_file"
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
  python-is-python3
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

ensure_mysql_build_deps || exit 1

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
ensure_python_build_deps || exit 1

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
fix_web_root_permissions

# ── Virtual environment ────────────────────────────────────────────────────────
mkdir -p "$BACKEND_DIR"

ensure_virtualenv

export PATH="$VENV_DIR/bin:$PATH"
hash -r
require_command python "The virtual environment should expose a python command."

log "📦 Upgrading pip, setuptools, wheel..."
pip_install install --upgrade pip setuptools wheel

# ── Install Python requirements ────────────────────────────────────────────────
REQUIREMENTS="$BACKEND_DIR/requirements.txt"
if [ -f "$REQUIREMENTS" ]; then
  log "📦 Installing Python requirements..."
  if ! pip_install install -r "$REQUIREMENTS"; then
    log "❌ Requirements installation failed — recent pip output:"
    tail -n 40 "$LOG_FILE" || true
    exit 1
  fi
  log "✅ Requirements installed"

  log "🔎 Verifying Python runtime packages..."
  if "$VENV_DIR/bin/python" - <<'PY' >>"$LOG_FILE" 2>&1
import importlib
import sys

required_modules = ["django", "celery", "gunicorn", "MySQLdb"]
missing = []

for module_name in required_modules:
    try:
        importlib.import_module(module_name)
    except Exception as exc:
        missing.append(f"{module_name}: {exc}")

if missing:
    for item in missing:
        print(item)
    sys.exit(1)
PY
  then
    log "✅ Python runtime packages verified"
  else
    log "❌ Python runtime package verification failed"
    log "❌ Recent runtime verification output:"
    tail -n 20 "$LOG_FILE"
    exit 1
  fi
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
