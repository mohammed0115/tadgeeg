#!/usr/bin/env bash
# ============================================================
# Tadgeeg — Live Server Update Script
# Usage:
#   bash deployment/docker/update.sh           # update live only
#   bash deployment/docker/update.sh all       # update live + dev + test
#   bash deployment/docker/update.sh live      # update live only
#   bash deployment/docker/update.sh dev       # update dev only
#   bash deployment/docker/update.sh test      # update test only
#
# What it does:
#   1. git pull latest code from origin/main
#   2. Rebuild Docker image(s)
#   3. Restart container(s) — entrypoint.sh auto-runs:
#      - migrate --noinput
#      - compilemessages
#      - collectstatic --noinput --clear
#   4. Show running containers and tail logs
# ============================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
TARGET="${1:-live}"
BRANCH="${BRANCH:-main}"

log() { printf '\n\033[1;34m[%s] %s\033[0m\n' "$(date '+%H:%M:%S')" "$1"; }
ok()  { printf '\033[1;32m  ✓ %s\033[0m\n' "$1"; }
err() { printf '\033[1;31m  ✗ %s\033[0m\n' "$1"; }

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

web_services_for_target() {
  case "$1" in
    live) echo "web_live celery_live" ;;
    dev)  echo "web_dev" ;;
    test) echo "web_test" ;;
    all)  echo "web_live celery_live web_dev web_test" ;;
    *)    err "Unknown target: $1 (live|dev|test|all)"; exit 1 ;;
  esac
}

all_services_for_target() {
  case "$1" in
    live) echo "redis db_live web_live celery_live nginx" ;;
    dev)  echo "redis db_dev web_dev nginx" ;;
    test) echo "redis db_test web_test nginx" ;;
    all)  echo "redis db_live web_live celery_live db_dev web_dev db_test web_test nginx" ;;
    *)    err "Unknown target: $1"; exit 1 ;;
  esac
}

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║       Tadgeeg Live Server Update             ║"
echo "╚══════════════════════════════════════════════╝"
echo "  Target  : $TARGET"
echo "  Branch  : $BRANCH"
echo "  Project : $PROJECT_ROOT"
echo ""

START_TIME=$(date +%s)

# ── 1. Git pull ────────────────────────────────────────────────────────────────
log "1/4  Pulling latest code from origin/$BRANCH ..."
cd "$PROJECT_ROOT"
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"
COMMIT=$(git log -1 --format="%h — %s (%ar)")
ok "HEAD: $COMMIT"

# ── 2. Ensure env files and nginx config exist ────────────────────────────────
log "2/4  Preparing runtime directories and config ..."
mkdir -p "$SCRIPT_DIR/nginx/generated" "$SCRIPT_DIR/certbot/www" "$SCRIPT_DIR/certbot/conf"

for env_name in live dev test; do
  target_file="$SCRIPT_DIR/env/${env_name}.env"
  example_file="$SCRIPT_DIR/env/${env_name}.env.example"
  if [ ! -f "$target_file" ]; then
    cp "$example_file" "$target_file"
    ok "Created env file: $target_file"
  fi
done

if [ ! -f "$SCRIPT_DIR/nginx/generated/default.conf" ]; then
  bash "$SCRIPT_DIR/render_nginx_config.sh" http
  ok "Generated nginx config"
else
  ok "Nginx config exists"
fi

# ── 3. Build + restart ────────────────────────────────────────────────────────
log "3/4  Building and restarting containers for [$TARGET] ..."
WEB_SERVICES=$(web_services_for_target "$TARGET")
ALL_SERVICES=$(all_services_for_target "$TARGET")

# Build updated web image(s) — no cache bust needed, code is COPY'd in
compose build --pull $WEB_SERVICES
ok "Build complete"

# Start/restart all relevant services
compose up -d $ALL_SERVICES
ok "Containers restarted"

# ── 4. Health check ───────────────────────────────────────────────────────────
log "4/4  Waiting for services to become healthy ..."
sleep 8

compose ps
echo ""

# Check web container logs for errors
for svc in $WEB_SERVICES; do
  echo "── Last 20 lines from $svc ──"
  compose logs --tail=20 "$svc" 2>&1 || true
  echo ""
done

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  ✅ Update COMPLETE                           ║"
echo "╚══════════════════════════════════════════════╝"
echo "  Target  : $TARGET"
echo "  Commit  : $COMMIT"
echo "  Duration: ${ELAPSED}s"
echo ""
echo "  Useful commands:"
echo "  bash deployment/docker/deploy.sh logs web_live   # follow logs"
echo "  bash deployment/docker/deploy.sh ps              # container status"
echo "  docker compose -f deployment/docker/docker-compose.yml exec web_live python manage.py shell"
