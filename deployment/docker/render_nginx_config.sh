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

source_env() {
  local env_name="$1"
  local file="$ENV_DIR/${env_name}.env"
  [ -f "$file" ] || {
    echo "Missing env file: $file"
    exit 1
  }

  set -a
  # shellcheck disable=SC1090
  source "$file"
  set +a
}

source_env live
LIVE_SERVER_NAMES="$SERVER_NAMES"
LIVE_CERT_NAME="$CERT_NAME"

source_env dev
DEV_SERVER_NAMES="$SERVER_NAMES"
DEV_CERT_NAME="$CERT_NAME"

source_env test
TEST_SERVER_NAMES="$SERVER_NAMES"
TEST_CERT_NAME="$CERT_NAME"

export LIVE_SERVER_NAMES LIVE_CERT_NAME DEV_SERVER_NAMES DEV_CERT_NAME TEST_SERVER_NAMES TEST_CERT_NAME

python3 - "$TEMPLATE_FILE" "$GENERATED_DIR/default.conf" <<'PY'
from pathlib import Path
import os
import sys

template = Path(sys.argv[1]).read_text(encoding='utf-8')
replacements = {
    '{{LIVE_SERVER_NAMES}}': os.environ['LIVE_SERVER_NAMES'],
    '{{LIVE_CERT_NAME}}': os.environ['LIVE_CERT_NAME'],
    '{{DEV_SERVER_NAMES}}': os.environ['DEV_SERVER_NAMES'],
    '{{DEV_CERT_NAME}}': os.environ['DEV_CERT_NAME'],
    '{{TEST_SERVER_NAMES}}': os.environ['TEST_SERVER_NAMES'],
    '{{TEST_CERT_NAME}}': os.environ['TEST_CERT_NAME'],
}

for old, new in replacements.items():
    template = template.replace(old, new)

Path(sys.argv[2]).write_text(template, encoding='utf-8')
PY

echo "Generated: $GENERATED_DIR/default.conf ($MODE)"
