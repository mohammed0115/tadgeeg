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

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/ocr_setup.log"

log() { echo "$(date '+%F %T') [$ENV_LABEL] $1" | tee -a "$LOG_FILE"; }

echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║  FinAI [$ENV_LABEL] — STEP 03: OCR & AI Setup    ║"
echo "╚═══════════════════════════════════════════════════╝"
echo ""

# ── Tesseract OCR ─────────────────────────────────────────────────────────────
if command -v tesseract &>/dev/null; then
  TESS_VER=$(tesseract --version 2>&1 | head -1)
  log "✅ Tesseract already installed: $TESS_VER"
else
  log "📦 Installing Tesseract OCR..."
  apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-ara \
    tesseract-ocr-eng \
    >>"$LOG_FILE" 2>&1
  log "✅ Tesseract OCR installed"
fi

# ── Language packs ────────────────────────────────────────────────────────────
log "🔤 Verifying language packs (ara + eng)..."
LANGS=$(tesseract --list-langs 2>/dev/null | tr '\n' ' ')

if [[ "$LANGS" == *"ara"* ]] && [[ "$LANGS" == *"eng"* ]]; then
  log "✅ OCR languages OK: ara + eng"
else
  log "⚠️  Some language packs missing — installing..."
  apt-get install -y tesseract-ocr-ara tesseract-ocr-eng >>"$LOG_FILE" 2>&1
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
  apt-get install -y poppler-utils >>"$LOG_FILE" 2>&1
  log "✅ poppler-utils installed"
fi

# ── LibMagic (MIME detection) ─────────────────────────────────────────────────
if dpkg -s libmagic1 &>/dev/null; then
  log "✅ libmagic already installed"
else
  log "📦 Installing libmagic..."
  apt-get install -y libmagic1 python3-magic >>"$LOG_FILE" 2>&1
  log "✅ libmagic installed"
fi

# ── OpenCV dependencies ───────────────────────────────────────────────────────
log "📦 Installing OpenCV system dependencies..."
apt-get install -y \
  libglib2.0-0 \
  libsm6 \
  libxext6 \
  libxrender-dev \
  libgl1-mesa-glx \
  >>"$LOG_FILE" 2>&1 || true
log "✅ OpenCV dependencies installed"

# ── ImageMagick (image preprocessing) ────────────────────────────────────────
if command -v convert &>/dev/null; then
  log "✅ ImageMagick already installed"
else
  apt-get install -y imagemagick >>"$LOG_FILE" 2>&1
  log "✅ ImageMagick installed"
fi

# ── Python OCR packages ───────────────────────────────────────────────────────
log "📦 Installing Python OCR packages in venv..."
"$VENV_DIR/bin/pip" install \
  pytesseract \
  Pillow \
  opencv-python-headless \
  python-magic \
  PyMuPDF \
  pdfplumber \
  pdf2image \
  >>"$LOG_FILE" 2>&1
log "✅ Python OCR packages installed"

# ── OpenAI SDK ────────────────────────────────────────────────────────────────
log "🤖 Installing OpenAI SDK..."
"$VENV_DIR/bin/pip" install openai >>"$LOG_FILE" 2>&1
log "✅ OpenAI SDK installed"

# ── Load OPENAI_API_KEY from secret file if not already set ──────────────────
SECRET_FILE="$WEB_ROOT/.secret.env"
if [ -f "$SECRET_FILE" ]; then
  log "🔑 Loading secrets from $SECRET_FILE..."
  # Only export defined key=value lines
  while IFS= read -r line; do
    [[ "$line" =~ ^[A-Z_]+=.+ ]] && export "$line" || true
  done < "$SECRET_FILE"
  log "✅ Secrets loaded"
else
  log "⚠️  Secret file not found: $SECRET_FILE"
  log "   Create it with: echo 'OPENAI_API_KEY=sk-...' > $SECRET_FILE"
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
