#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
RENDER_SCRIPT="$SCRIPT_DIR/render_nginx_config.sh"
ENV_DIR="$SCRIPT_DIR/env"

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

require_docker() {
  command -v docker >/dev/null 2>&1 || {
    echo "Docker غير مثبت"
    exit 1
  }
}

prepare_directories() {
  mkdir -p "$SCRIPT_DIR/nginx/generated" "$SCRIPT_DIR/certbot/www" "$SCRIPT_DIR/certbot/conf"
}

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

issue_cert() {
  local env_name="$1"
  local file="$ENV_DIR/${env_name}.env"

  load_env_file "$file"

  [ -n "${SERVER_NAMES:-}" ] || {
    echo "SERVER_NAMES missing in $file"
    exit 1
  }

  [ -n "${CERT_NAME:-}" ] || {
    echo "CERT_NAME missing in $file"
    exit 1
  }

  local email="${SSL_EMAIL:-${EMAIL_HOST_USER:-}}"
  [ -n "$email" ] || {
    echo "SSL_EMAIL أو EMAIL_HOST_USER مطلوب في $file"
    exit 1
  }

  local domain_args=()
  for domain in $SERVER_NAMES; do
    domain_args+=("-d" "$domain")
  done

  compose run --rm certbot certonly \
    --webroot -w /var/www/certbot \
    --email "$email" \
    --agree-tos \
    --no-eff-email \
    --cert-name "$CERT_NAME" \
    "${domain_args[@]}"
}

require_docker
prepare_directories

bash "$RENDER_SCRIPT" http
compose up -d nginx

issue_cert live
issue_cert dev
issue_cert test

bash "$RENDER_SCRIPT" https
compose up -d nginx
compose exec nginx nginx -s reload

echo "HTTPS enabled successfully for live, dev, test."
