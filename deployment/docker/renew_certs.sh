#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
RENDER_SCRIPT="$SCRIPT_DIR/render_nginx_config.sh"

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

bash "$RENDER_SCRIPT" https
compose run --rm certbot renew --webroot -w /var/www/certbot
compose exec nginx nginx -s reload

echo "Certificates renewed and nginx reloaded."
