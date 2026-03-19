#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-http}"
ENV_DIR="$SCRIPT_DIR/env"
NGINX_DIR="$SCRIPT_DIR/nginx"
GENERATED_DIR="$NGINX_DIR/generated"

mkdir -p "$GENERATED_DIR"

case "$MODE" in
  http) TEMPLATE_FILE="$NGINX_DIR/http.conf.template" ;;
  https) TEMPLATE_FILE="$NGINX_DIR/https.conf.template" ;;
  *)
    echo "Unknown mode: $MODE"
    exit 1
    ;;
esac

load_env_file() {
  local file="$1"
  [ -f "$file" ] || {
    echo "Missing env file: $file"
    exit 1
  }

  while IFS= read -r raw_line || [ -n "$raw_line" ]; do
    local line="${raw_line%$'\r'}"

    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" == *=* ]] || continue

    local key="${line%%=*}"
    local value="${line#*=}"

    export "$key=$value"
  done < "$file"
}

load_env_file "$ENV_DIR/live.env"
LIVE_SERVER_NAMES="${SERVER_NAMES:-tadgeeg.com www.tadgeeg.com}"
LIVE_CERT_NAME="${CERT_NAME:-tadgeeg.com}"
LIVE_PRIMARY_DOMAIN="$(echo "$LIVE_SERVER_NAMES" | awk '{print $1}')"

load_env_file "$ENV_DIR/dev.env"
DEV_SERVER_NAMES="${SERVER_NAMES:-dev.tadgeeg.com}"
DEV_CERT_NAME="${CERT_NAME:-dev.tadgeeg.com}"

load_env_file "$ENV_DIR/test.env"
TEST_SERVER_NAMES="${SERVER_NAMES:-test.tadgeeg.com}"
TEST_CERT_NAME="${CERT_NAME:-test.tadgeeg.com}"

export LIVE_SERVER_NAMES LIVE_CERT_NAME LIVE_PRIMARY_DOMAIN \
       DEV_SERVER_NAMES DEV_CERT_NAME \
       TEST_SERVER_NAMES TEST_CERT_NAME

python3 - "$TEMPLATE_FILE" "$GENERATED_DIR/default.conf" <<'PY'
from pathlib import Path
import os
import sys

template = Path(sys.argv[1]).read_text(encoding='utf-8')
replacements = {
    '{{LIVE_SERVER_NAMES}}':   os.environ['LIVE_SERVER_NAMES'],
    '{{LIVE_CERT_NAME}}':      os.environ['LIVE_CERT_NAME'],
    '{{LIVE_PRIMARY_DOMAIN}}': os.environ['LIVE_PRIMARY_DOMAIN'],
    '{{DEV_SERVER_NAMES}}':    os.environ['DEV_SERVER_NAMES'],
    '{{DEV_CERT_NAME}}':       os.environ['DEV_CERT_NAME'],
    '{{TEST_SERVER_NAMES}}':   os.environ['TEST_SERVER_NAMES'],
    '{{TEST_CERT_NAME}}':      os.environ['TEST_CERT_NAME'],
}

for old, new in replacements.items():
    template = template.replace(old, new)

Path(sys.argv[2]).write_text(template, encoding='utf-8')
PY

echo "Generated: $GENERATED_DIR/default.conf ($MODE)"
echo "  live  → $LIVE_SERVER_NAMES"
echo "  dev   → $DEV_SERVER_NAMES"
echo "  test  → $TEST_SERVER_NAMES"
