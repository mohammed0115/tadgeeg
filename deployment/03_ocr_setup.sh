#!/bin/bash
# ============================================================
# FinAI Deployment — Step 03: OCR & AI Setup
# Usage: bash 03_ocr_setup.sh [live|dev|test]
# Installs: Tesseract (ara+eng), Poppler, OpenCV deps
# Also sets OPENAI_API_KEY from secret file if available
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV="${1:-live}"

ENV_FILE="$SCRIPT_DIR/config/${ENV}.env"
[ -f "$ENV_FILE" ] || { echo "❌ Unknown environment: $ENV"; exit 1; }
source "$ENV_FILE"
export DEBIAN_FRONTEND=noninteractive

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/ocr_setup.log"

log() { echo "$(date '+%F %T') [$ENV_LABEL] $1" | tee -a "$LOG_FILE"; }

APT_RETRY_COUNT="${APT_RETRY_COUNT:-3}"
APT_UPDATED=false

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

ensure_apt_cache() {
  if [ "$APT_UPDATED" != "true" ]; then
    apt_update
    APT_UPDATED=true
  fi
}

apt_install() {
  [ "$#" -gt 0 ] || return 0
  ensure_apt_cache
  run_with_retries "apt-get install: $*" apt-get install -y "$@"
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
      log "❌ python3.12 is required before OCR setup. Run deployment/02_system_setup.sh first."
      exit 1
    }

    log "🐍 Creating virtual environment for OCR tools..."
    python3.12 -m venv "$VENV_DIR"
  fi

  if [ ! -x "$VENV_DIR/bin/pip" ]; then
    log "🔧 Bootstrapping pip inside the OCR virtual environment..."
    "$VENV_DIR/bin/python" -m ensurepip --upgrade >>"$LOG_FILE" 2>&1
  fi
}

load_secret_env() {
  local secret_file="$1"
  [ -f "$secret_file" ] || return 0

  while IFS= read -r line; do
    [[ "$line" =~ ^[A-Z_]+=.+ ]] && export "$line" || true
  done < "$secret_file"
}

echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║  FinAI [$ENV_LABEL] — STEP 03: OCR & AI Setup    ║"
echo "╚═══════════════════════════════════════════════════╝"
echo ""

ensure_virtualenv
log "📦 Upgrading pip, setuptools, wheel in OCR venv..."
pip_install install --upgrade pip setuptools wheel

# ── Tesseract OCR ─────────────────────────────────────────────────────────────
if command -v tesseract &>/dev/null; then
  TESS_VER=$(tesseract --version 2>&1 | head -1)
  log "✅ Tesseract already installed: $TESS_VER"
else
  log "📦 Installing Tesseract OCR..."
  apt_install \
    tesseract-ocr \
    tesseract-ocr-ara \
    tesseract-ocr-eng
  log "✅ Tesseract OCR installed"
fi

# ── Language packs ────────────────────────────────────────────────────────────
log "🔤 Verifying language packs (ara + eng)..."
LANGS=$(tesseract --list-langs 2>/dev/null | tr '\n' ' ')

if [[ "$LANGS" == *"ara"* ]] && [[ "$LANGS" == *"eng"* ]]; then
  log "✅ OCR languages OK: ara + eng"
else
  log "⚠️  Some language packs missing — installing..."
  apt_install tesseract-ocr-ara tesseract-ocr-eng
  log "✅ Language packs installed"
fi

# ── TESSDATA path ─────────────────────────────────────────────────────────────
# Find tessdata — path varies by Tesseract version
TESS_PATH=""
for CANDIDATE in \
  "/usr/share/tesseract-ocr/5/tessdata" \
  "/usr/share/tesseract-ocr/4.00/tessdata" \
  "/usr/share/tessdata" \
  "/usr/local/share/tessdata"; do
  if [ -d "$CANDIDATE" ]; then
    TESS_PATH="$CANDIDATE"
    break
  fi
done

if [ -z "$TESS_PATH" ]; then
  log "❌ Could not locate TESSDATA directory"
  exit 1
fi
log "✅ TESSDATA path: $TESS_PATH"

# ── Set TESSDATA_PREFIX globally ──────────────────────────────────────────────
ENV_SYS="/etc/environment"
if grep -q "TESSDATA_PREFIX" "$ENV_SYS" 2>/dev/null; then
  # Update existing entry
  sed -i "s|^TESSDATA_PREFIX=.*|TESSDATA_PREFIX=$TESS_PATH|" "$ENV_SYS"
  log "🔧 Updated TESSDATA_PREFIX in $ENV_SYS"
else
  echo "TESSDATA_PREFIX=$TESS_PATH" >> "$ENV_SYS"
  log "🔧 Added TESSDATA_PREFIX to $ENV_SYS"
fi
export TESSDATA_PREFIX="$TESS_PATH"

# ── Poppler (PDF → image conversion) ─────────────────────────────────────────
if command -v pdftoppm &>/dev/null; then
  log "✅ poppler-utils already installed"
else
  log "📦 Installing poppler-utils..."
  apt_install poppler-utils
  log "✅ poppler-utils installed"
fi

# ── LibMagic (MIME detection) ─────────────────────────────────────────────────
if dpkg -s libmagic1 &>/dev/null; then
  log "✅ libmagic already installed"
else
  log "📦 Installing libmagic..."
  apt_install libmagic1 python3-magic
  log "✅ libmagic installed"
fi

# ── OpenCV dependencies ───────────────────────────────────────────────────────
log "📦 Installing OpenCV system dependencies..."
apt_install \
  libglib2.0-0 \
  libsm6 \
  libxext6 \
  libxrender-dev

if ! apt_install libgl1-mesa-glx; then
  log "⚠️  libgl1-mesa-glx unavailable — trying libgl1 instead"
  apt_install libgl1 || log "⚠️  Optional libgl package could not be installed — headless OpenCV may still work"
fi
log "✅ OpenCV dependencies installed"

# ── ImageMagick (image preprocessing) ────────────────────────────────────────
if command -v convert &>/dev/null; then
  log "✅ ImageMagick already installed"
else
  apt_install imagemagick
  log "✅ ImageMagick installed"
fi

# ── Python OCR packages ───────────────────────────────────────────────────────
log "📦 Installing Python OCR packages in venv..."
pip_install install \
  pytesseract \
  Pillow \
  opencv-python-headless \
  python-magic \
  PyMuPDF \
  pdfplumber \
  pdf2image
log "✅ Python OCR packages installed"

# ── OpenAI SDK ────────────────────────────────────────────────────────────────
log "🤖 Installing OpenAI SDK..."
pip_install install openai
log "✅ OpenAI SDK installed"

# ── Load OPENAI_API_KEY from secret file if not already set ──────────────────
SECRET_FILE="$WEB_ROOT/.secret.env"
if [ -f "$SECRET_FILE" ]; then
  log "🔑 Loading secrets from $SECRET_FILE..."
  load_secret_env "$SECRET_FILE"
  log "✅ Secrets loaded"
else
  log "⚠️  Secret file not found: $SECRET_FILE"
  log "   Create it with: echo 'OPENAI_API_KEY=sk-...' > $SECRET_FILE"
fi

log "🔎 Verifying OCR Python packages..."
"$VENV_DIR/bin/python" -c "import fitz, magic, openai, pdf2image, pdfplumber, PIL, pytesseract; import cv2" >>"$LOG_FILE" 2>&1 || {
  log "❌ OCR Python package verification failed"
  tail -n 40 "$LOG_FILE" || true
  exit 1
}
log "✅ OCR Python packages verified"

if [ -n "${OPENAI_API_KEY:-}" ]; then
  log "✅ OPENAI_API_KEY is configured"
else
  log "⚠️  OPENAI_API_KEY is not configured yet — OCR works, but AI calls will fail until it is set"
fi

# ── Smoke test Tesseract ──────────────────────────────────────────────────────
log "🔍 Smoke-testing Tesseract..."
TESS_TEST=$(echo "test" | tesseract stdin stdout 2>/dev/null | head -1 || echo "")
if [ -n "$TESS_TEST" ] || tesseract --list-langs 2>&1 | grep -q "ara"; then
  log "✅ Tesseract smoke test passed"
else
  log "⚠️  Tesseract smoke test inconclusive (may still work)"
fi

echo ""
echo "✅ [STEP 03] OCR & AI Setup COMPLETED for [$ENV_LABEL]"
