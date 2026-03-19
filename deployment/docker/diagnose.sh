#!/usr/bin/env bash
# ============================================================
# Tadgeeg — Server Diagnostic Script
# Run on the live server to diagnose 502/404 issues:
#   bash deployment/docker/diagnose.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

HR="══════════════════════════════════════════════"

section() { echo ""; echo "$HR"; echo "  $1"; echo "$HR"; }

section "1. Container Status"
compose ps 2>&1 || echo "Docker Compose not running"

section "2. web_live last 40 log lines"
compose logs --tail=40 web_live 2>&1 || echo "web_live not running"

section "3. Redis status"
compose ps redis 2>&1
compose exec redis redis-cli ping 2>&1 || echo "Redis not reachable"

section "4. Nginx config"
cat "$SCRIPT_DIR/nginx/generated/default.conf" 2>/dev/null || echo "No nginx config generated"

section "5. Nginx last 20 log lines"
compose logs --tail=20 nginx 2>&1 || echo "Nginx not running"

section "6. live.env key values (no passwords)"
awk -F= '
  /^(ALLOWED_HOSTS|SERVER_NAMES|DEBUG|DB_HOST|DB_NAME|REDIS_URL|DJANGO_SETTINGS_MODULE|SITE_URL)=/ {print}
' "$SCRIPT_DIR/env/live.env" 2>/dev/null || echo "live.env not found"

section "7. Port 8000 inside web_live"
compose exec web_live sh -c "ss -tlnp 2>/dev/null | grep 8000 || netstat -tlnp 2>/dev/null | grep 8000 || echo 'port check unavailable'" 2>&1 || echo "web_live not running"

section "8. Quick HTTP test (internal)"
compose exec nginx sh -c "wget -qO- --timeout=5 http://web_live:8000/health/ 2>&1 || curl -sf --max-time 5 http://web_live:8000/health/ 2>&1 || echo 'Cannot reach web_live:8000'" 2>&1 || echo "Cannot exec into nginx"

echo ""
echo "$HR"
echo "  Diagnostic complete — copy all output above and share it"
echo "$HR"
