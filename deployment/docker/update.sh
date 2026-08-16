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

# Branch: the second argument, else $BRANCH, else whatever is checked out, else
# main. It used to default to main unconditionally, so
#
#     git checkout my-branch && bash update.sh dev
#
# fetched main and `git reset --hard origin/main` — which does not merely
# ignore your branch, it MOVES the local branch ref you are standing on to
# main's commit. The deploy then reported success having shipped main. That is
# how this deploy silently shipped the wrong code a moment ago.
#
# Defaulting to the current branch makes the obvious sequence do the obvious
# thing; `bash update.sh dev main` or BRANCH=main still forces main.
CURRENT_BRANCH="$(git -C "$PROJECT_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
[ "$CURRENT_BRANCH" = "HEAD" ] && CURRENT_BRANCH=main   # detached
BRANCH="${2:-${BRANCH:-$CURRENT_BRANCH}}"

log() { printf '\n\033[1;34m[%s] %s\033[0m\n' "$(date '+%H:%M:%S')" "$1"; }
ok()  { printf '\033[1;32m  ✓ %s\033[0m\n' "$1"; }
err() { printf '\033[1;31m  ✗ %s\033[0m\n' "$1"; }

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

backup_live_database() {
  # Migrations are writers. A deploy must never mutate the live schema without
  # a restorable, point-in-time dump created before code or containers change.
  case "$TARGET" in
    live|all) ;;
    *) return 0 ;;
  esac

  local backup_root="$PROJECT_ROOT/backups/mysql/live"
  local stamp dump_tmp dump_gz checksum
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  dump_tmp="$backup_root/tadgeeg-live-${stamp}.sql"
  dump_gz="${dump_tmp}.gz"
  checksum="${dump_gz}.sha256"

  if ! compose ps --status running --services 2>/dev/null | grep -qx "db_live"; then
    err "db_live is not running; cannot create the mandatory pre-migration backup."
    exit 1
  fi

  umask 077
  mkdir -p "$backup_root"
  log "Creating pre-migration MySQL backup ..."
  if ! compose exec -T db_live sh -c \
    'exec mysqldump --single-transaction --routines --events --hex-blob -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' \
    > "$dump_tmp"; then
    rm -f "$dump_tmp"
    err "Pre-migration database backup failed; deployment aborted."
    exit 1
  fi

  if [ ! -s "$dump_tmp" ]; then
    rm -f "$dump_tmp"
    err "Pre-migration database backup was empty; deployment aborted."
    exit 1
  fi

  gzip -f "$dump_tmp"
  sha256sum "$dump_gz" > "$checksum"
  ok "Pre-migration backup: $dump_gz"
}

# Which env files a target needs. Referenced by the pre-flight checks below.
envs_for_target() {
  case "$1" in
    live) echo "live" ;;
    dev)  echo "dev" ;;
    test) echo "test" ;;
    all)  echo "live dev test" ;;
    *)    echo "live" ;;
  esac
}

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

# ── 1. Database backup + Git pull ─────────────────────────────────────────────
log "1/4  Backing up live data and pulling latest code from origin/$BRANCH ..."
cd "$PROJECT_ROOT"
backup_live_database

# Safety net: preserve env files across the git reset. They are gitignored
# today, but git reset --hard would still wipe them if a future commit ever
# accidentally tracks them. Snapshot to a temp dir and restore byte-for-byte
# after the reset so secrets survive every redeploy.
ENV_BACKUP_DIR="$(mktemp -d -t finai-env-backup-XXXXXX)"
trap 'rm -rf "$ENV_BACKUP_DIR"' EXIT
shopt -s nullglob
for env_file in "$SCRIPT_DIR"/env/*.env; do
  cp -p "$env_file" "$ENV_BACKUP_DIR/$(basename "$env_file")"
  ok "Backed up $(basename "$env_file")"
done
shopt -u nullglob

if ! git fetch origin "$BRANCH"; then
  err "Branch '$BRANCH' not found on origin."
  echo "    Push it first, or pass the branch: bash update.sh $TARGET <branch>"
  exit 1
fi

# Say what is about to be discarded. `reset --hard` is silent about local
# commits, and a deploy is exactly when someone discovers a hotfix only ever
# existed on the server.
BEHIND_BY=$(git rev-list --count "origin/$BRANCH..HEAD" 2>/dev/null || echo 0)
if [ "$BEHIND_BY" -gt 0 ]; then
  err "$BEHIND_BY local commit(s) on this checkout are NOT on origin/$BRANCH."
  git log --oneline "origin/$BRANCH..HEAD" | sed 's/^/      /'
  echo "    reset --hard would discard them. Push or stash them, then re-run."
  exit 1
fi

git reset --hard "origin/$BRANCH"
COMMIT=$(git log -1 --format="%h — %s (%ar)")
ok "HEAD: $COMMIT  [$BRANCH]"

# Restore env files in case the reset removed or modified them.
for backup in "$ENV_BACKUP_DIR"/*.env; do
  [ -e "$backup" ] || continue
  cp -p "$backup" "$SCRIPT_DIR/env/$(basename "$backup")"
  ok "Restored $(basename "$backup")"
done

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

# Always re-render from the template, in whichever mode is already in force.
# This previously ran only when the generated file was missing — and it is
# committed, so it never ran and template edits never reached the server.
# The mode is detected, not assumed: rendering http over a live HTTPS site
# would downgrade it.
NGINX_MODE="http"
if [ -f "$SCRIPT_DIR/nginx/generated/default.conf" ] \
   && grep -q "listen 443" "$SCRIPT_DIR/nginx/generated/default.conf"; then
  NGINX_MODE="https"
fi
bash "$SCRIPT_DIR/render_nginx_config.sh" "$NGINX_MODE"
ok "Rendered nginx config from template (mode: $NGINX_MODE)"

# ── 2b. Guards that would otherwise fail AFTER the containers start ──────────
# Everything below was learned from a real outage: a root-owned volume made
# Django raise PermissionError at import, gunicorn never bound, and nginx
# served 502 for an hour while the entrypoint printed "Database unavailable".
log "2b/4  Pre-flight checks ..."

# (a) required env keys — an env file created before these phases passes the
#     "file exists" check while silently missing keys, and the app then falls
#     back to a default. For PARTNER_DOCS_ROOT that default is inside the
#     container, on no volume, so uploads die on the next rebuild.
REQUIRED_KEYS="PARTNER_DOCS_ROOT PARTNER_DOC_MAX_FILE_MB PARTNER_DOC_MAX_TOTAL_MB
PARTNER_DOC_MAX_FILES PARTNER_APPLICATION_DEDUPE_MINUTES
THROTTLE_PARTNER_APPLICATION THROTTLE_PUBLIC_CONTACT THROTTLE_PRICING_CALCULATOR"

for env_name in $(envs_for_target "$TARGET"); do
  env_file="$SCRIPT_DIR/env/${env_name}.env"
  for key in $REQUIRED_KEYS; do
    if ! grep -qE "^[[:space:]]*${key}=" "$env_file"; then
      err "Missing key '${key}' in ${env_file}"
      echo "    انسخه من ${env_name}.env.example ثم أعد المحاولة."
      exit 1
    fi
  done
  docs_root="$(grep -E "^[[:space:]]*PARTNER_DOCS_ROOT=" "$env_file" | tail -1 | cut -d= -f2-)"
  case "$docs_root" in
    */media/*|/app/media*)
      err "PARTNER_DOCS_ROOT is inside the PUBLIC media root: $docs_root"
      echo "    nginx يخدم /media/ علنًا — سجل تجاري لطرف ثالث سيصبح قابلًا للتنزيل."
      exit 1 ;;
  esac
done
ok "Env keys present, PARTNER_DOCS_ROOT outside the media root"

# (b) volume ownership. Docker creates a NEW named volume owned by root; the
#     container runs as www-data. Django creates MEDIA_ROOT and
#     PARTNER_DOCS_ROOT at import, so a root-owned volume stops the app before
#     it can report anything useful. Idempotent — safe on every deploy.
for svc in $(web_services_for_target "$TARGET"); do
  if compose ps --status running --services 2>/dev/null | grep -q "^${svc}$"; then
    compose exec -T -u root "$svc" \
      sh -c 'chown -R www-data:www-data /app/private_media /app/media /app/staticfiles /app/logs 2>/dev/null' \
      >/dev/null 2>&1 || true
  fi
done
ok "Volume ownership normalised (www-data)"

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

# A volume created for the FIRST time during the `up` above is root-owned and
# the container is already failing on it. Fix and restart once — this is the
# exact failure that took production down.
sleep 5
for svc in $(web_services_for_target "$TARGET"); do
  if compose logs --tail=20 "$svc" 2>/dev/null | grep -q "Permission denied"; then
    err "$svc cannot write to a mounted volume — fixing ownership and restarting"
    compose exec -T -u root "$svc" \
      sh -c 'chown -R www-data:www-data /app/private_media /app/media /app/staticfiles /app/logs' \
      >/dev/null 2>&1 \
      || compose run --rm -u root "$svc" \
           chown -R www-data:www-data /app/private_media /app/media /app/staticfiles /app/logs \
           >/dev/null 2>&1 || true
    compose up -d "$svc"
    ok "$svc restarted after ownership fix"
  fi
done

# ── 3b. Migrations — verify, do not assume ───────────────────────────────────
# The entrypoint runs `migrate` at container start. If it FAILED, the container
# exits and the site is down; if it was skipped, every query against a new
# column throws and the billing context processor swallows it into a silently
# missing menu. Neither is acceptable to discover from a user report.
log "3b/4  Verifying migrations ..."

for svc in $(web_services_for_target "$TARGET"); do
  # Wait for the entrypoint to FINISH, not merely for the container to exist.
  #
  # `python -c "import django"` was the wrong signal: `compose exec` starts a
  # NEW process, which succeeds the moment the container runs — while the
  # entrypoint is still applying migrations. That reported "40 unapplied
  # migrations" for migrations that were being applied at that exact moment.
  #
  # The honest signal is the entrypoint's last act: gunicorn binding port 8000.
  # celery has no port, so it waits for its own process instead.
  printf '  waiting for %s ' "$svc"
  ready=0
  for _ in $(seq 1 120); do
    case "$svc" in
      celery*)
        # `pgrep -f "celery.*worker"` was the check, and it could never pass:
        # python:3.12-slim ships without procps, so pgrep does not exist in the
        # image. Every deploy waited the full ten minutes and then declared a
        # worker dead that had logged "celery@… ready" minutes earlier.
        #
        # `inspect ping` is the better signal anyway, not merely a working one.
        # A process existing proves nothing: a worker that cannot reach Redis,
        # or is stuck importing, still shows up in a process list. A pong came
        # back over the broker, which is the thing that has to work.
        compose exec -T "$svc" celery -A finai_backend inspect ping --timeout 5 2>/dev/null \
          | grep -q "pong" \
          && { ready=1; printf ' ready\n'; break; } ;;
      *)
        compose exec -T "$svc" sh -c \
          'python -c "import socket,sys; s=socket.socket(); sys.exit(s.connect_ex((\"127.0.0.1\",8000)))"' \
          >/dev/null 2>&1 \
          && { ready=1; printf ' ready\n'; break; } ;;
    esac
    # A container that exited is never going to become ready.
    if ! compose ps --status running --services 2>/dev/null | grep -q "^${svc}$"; then
      printf '\n'
      err "$svc stopped while starting. Last 40 log lines:"
      compose logs --tail=40 "$svc" || true
      exit 1
    fi
    printf '.'
    sleep 5
  done
  [ "$ready" -eq 1 ] || {
    printf '\n'
    err "$svc never became ready. Last 40 log lines:"
    compose logs --tail=40 "$svc" || true
    exit 1
  }

  # The migration checks below query the DATABASE, and web + celery share one.
  # Running them again against the worker asks the same question of the same
  # database and costs a minute per deploy for an answer already given.
  case "$svc" in
    celery*) ok "$svc: ready (migrations verified via its web counterpart)"; continue ;;
  esac

  # showmigrations --plan marks unapplied ones with "[ ]".
  UNAPPLIED="$(compose exec -T "$svc" python manage.py showmigrations --plan 2>/dev/null \
                | grep -c '^\[ \]' || true)"
  if [ "${UNAPPLIED:-0}" -gt 0 ]; then
    err "$svc has $UNAPPLIED UNAPPLIED migration(s) — the database is behind the code."
    compose exec -T "$svc" python manage.py showmigrations --plan 2>/dev/null \
      | grep '^\[ \]' | head -20 || true
    echo
    echo "    شغّلها يدويًا ثم تحقّق:"
    echo "      docker compose -f $COMPOSE_FILE exec $svc python manage.py migrate"
    exit 1
  fi
  ok "$svc: all migrations applied"

  # A model change with no migration file is the mirror image of the same
  # problem, and just as invisible until a query fails.
  if ! compose exec -T "$svc" python manage.py makemigrations --check --dry-run >/dev/null 2>&1; then
    err "$svc: model changes exist with no migration file. Run makemigrations."
    exit 1
  fi
  ok "$svc: no missing migration files"
done

# ── 4. Health check ───────────────────────────────────────────────────────────
log "4/4  Waiting for services to become healthy ..."

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
