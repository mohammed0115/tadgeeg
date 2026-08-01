#!/usr/bin/env bash
# ============================================================================
# Tadgeeg — redeploy one environment, safely.
#
#   bash deployment/docker/redeploy.sh              # live (default)
#   bash deployment/docker/redeploy.sh dev
#   bash deployment/docker/redeploy.sh live --no-pull      # deploy current HEAD
#   bash deployment/docker/redeploy.sh live --skip-backup  # you own the risk
#
# What it does, in order:
#   0. refuse to run if the env files are missing required keys
#   1. back up the database  (skippable, never silently)
#   2. git pull
#   3. re-render nginx from the TEMPLATE, preserving http/https mode
#   4. build + start   → entrypoint.sh then runs, inside the container:
#         migrate → compilemessages → collectstatic
#               → seed_billing_plans → seed_addons → seed_partners
#   5. post-deploy verification, including the private-document leak gate
#
# Every step stops the deploy on failure. A half-migrated database that keeps
# serving traffic is worse than a deploy that stopped and said so.
# ============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"

TARGET="live"
DO_PULL=1
DO_BACKUP=1
for arg in "$@"; do
  case "$arg" in
    live|dev|test) TARGET="$arg" ;;
    --no-pull)     DO_PULL=0 ;;
    --skip-backup) DO_BACKUP=0 ;;
    -h|--help)     sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

log()  { printf '\n\033[1;34m▶ %s\033[0m\n' "$1"; }
ok()   { printf '\033[1;32m  ✓ %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$1"; }
die()  { printf '\n\033[1;31m✗ DEPLOY STOPPED: %s\033[0m\n' "$1" >&2; exit 1; }

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

# Read ONE value from an env file without sourcing it.
#
# These files contain unquoted values with spaces (SERVER_NAMES=a.com www.a.com),
# so `. file` makes the shell try to execute the second word as a command.
# `cut -d= -f2-` keeps '=' characters inside passwords intact.
env_value() {  # key file
  grep -E "^[[:space:]]*$1=" "$2" | tail -1 | cut -d= -f2- | sed 's/^["'"'"']//; s/["'"'"']$//'
}


case "$TARGET" in
  live) WEB=web_live;  DB=db_live;  DOMAIN=tadgeeg.com ;;
  dev)  WEB=web_dev;   DB=db_dev;   DOMAIN=dev.tadgeeg.com ;;
  test) WEB=web_test;  DB=db_test;  DOMAIN=test.tadgeeg.com ;;
esac

echo "════════════════════════════════════════════════"
echo "  Redeploy: $TARGET   ($DOMAIN)"
echo "════════════════════════════════════════════════"

# ── 0. Environment sanity ───────────────────────────────────────────────────
# Runs BEFORE the backup so a missing key costs nothing. `deploy.sh up` runs the
# same checks; doing them here too means this script fails in seconds rather
# than after a database dump.
log "0/5  Checking environment files"
ENV_FILE="$SCRIPT_DIR/env/${TARGET}.env"
[ -f "$ENV_FILE" ] || die "Missing $ENV_FILE — run: bash deployment/docker/deploy.sh init-env"

for key in PARTNER_DOCS_ROOT PARTNER_DOC_MAX_FILE_MB PARTNER_DOC_MAX_TOTAL_MB \
           PARTNER_DOC_MAX_FILES PARTNER_APPLICATION_DEDUPE_MINUTES \
           THROTTLE_PARTNER_APPLICATION THROTTLE_PUBLIC_CONTACT \
           THROTTLE_PRICING_CALCULATOR; do
  grep -qE "^[[:space:]]*${key}=" "$ENV_FILE" \
    || die "Missing key '${key}' in ${ENV_FILE} — copy it from ${TARGET}.env.example"
done

DOCS_ROOT="$(grep -E '^[[:space:]]*PARTNER_DOCS_ROOT=' "$ENV_FILE" | tail -1 | cut -d= -f2-)"
case "$DOCS_ROOT" in
  */media/*|/app/media*)
    die "PARTNER_DOCS_ROOT is inside the public media root ($DOCS_ROOT).
     nginx serves /media/ publicly — a third party's commercial register
     would be downloadable by guessing a URL." ;;
esac
ok "Environment keys present, PARTNER_DOCS_ROOT outside the media root"

# ── 1. Database backup ──────────────────────────────────────────────────────
log "1/5  Database backup"
if [ "$DO_BACKUP" -eq 1 ]; then
  BACKUP_DIR="$SCRIPT_DIR/backups"
  mkdir -p "$BACKUP_DIR"
  STAMP="$(date +%Y%m%d-%H%M%S)"
  BACKUP_FILE="$BACKUP_DIR/${TARGET}-${STAMP}.sql.gz"
  if compose ps --status running --services 2>/dev/null | grep -q "^${DB}$"; then
    # Credentials come from the DB container's own environment — never echoed
    # here, and never sourced (see env_value above).
    compose exec -T "$DB" sh -c \
      'exec mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" --single-transaction --quick "$MYSQL_DATABASE"' \
      | gzip > "$BACKUP_FILE" \
      || die "Backup failed. Not deploying — this deploy applies migrations."
    ok "Backup: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
  else
    warn "$DB is not running — nothing to back up (first deploy?)"
  fi
else
  warn "Backup SKIPPED by --skip-backup. This deploy applies migrations."
fi

# ── 2. Code ─────────────────────────────────────────────────────────────────
log "2/5  Source"
cd "$PROJECT_ROOT"
if [ "$DO_PULL" -eq 1 ]; then
  # Only fetch/pull when actually behind. Operators normally run `git pull`
  # themselves first, and pulling again over HTTPS asks for a GitHub password
  # a second time for no gain.
  BRANCH_NAME="$(git rev-parse --abbrev-ref HEAD)"
  if git fetch --quiet origin "$BRANCH_NAME" 2>/dev/null \
     && [ -n "$(git rev-list --count HEAD..origin/"$BRANCH_NAME" 2>/dev/null)" ] \
     && [ "$(git rev-list --count HEAD..origin/"$BRANCH_NAME")" -gt 0 ]; then
    git pull --ff-only || die "git pull failed (local changes or diverged history?)"
  else
    ok "Already at the latest commit — no pull needed"
  fi
fi
ok "HEAD: $(git rev-parse --short HEAD) — $(git log -1 --pretty=%s)"

# ── 3. nginx ────────────────────────────────────────────────────────────────
# Re-rendered every time, in whichever mode is in force. This used to run only
# when the generated file was missing — and it is committed, so it never ran and
# template edits never reached the server.
log "3/5  Rendering nginx from template"
NGINX_MODE="http"
if [ -f "$SCRIPT_DIR/nginx/generated/default.conf" ] \
   && grep -q "listen 443" "$SCRIPT_DIR/nginx/generated/default.conf"; then
  NGINX_MODE="https"
fi
bash "$SCRIPT_DIR/render_nginx_config.sh" "$NGINX_MODE" >/dev/null \
  || die "nginx render failed"
ok "Rendered (mode: $NGINX_MODE)"

# ── 4. Build and start ──────────────────────────────────────────────────────
log "4/5  Build and start"
# deploy.sh takes ACTION first, TARGET second (deploy.sh:6-7).
bash "$SCRIPT_DIR/deploy.sh" up "$TARGET" \
  || die "Build/start failed. The entrypoint runs migrate, compilemessages,
     collectstatic and the seeds — check the container logs:
       docker compose -f $COMPOSE_FILE logs --tail=80 $WEB"
ok "Containers up"

compose exec -T nginx nginx -s reload >/dev/null 2>&1 \
  && ok "nginx reloaded" || warn "nginx reload skipped (not running?)"

# ── 5. Verification ─────────────────────────────────────────────────────────
log "5/5  Post-deploy verification"

# Wait for the app to answer rather than guessing at a duration. The entrypoint
# runs migrations, compilemessages, collectstatic and three seeds before
# gunicorn binds — on a first deploy of several phases that is well over a
# fixed 6s, and a short sleep would report a healthy deploy as broken.
printf '  waiting for %s ' "$DOMAIN"
for _ in $(seq 1 60); do
  if [ "$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 "https://${DOMAIN}/" || echo 000)" = "200" ]; then
    printf ' up\n'
    break
  fi
  printf '.'
  sleep 5
done
echo

check() {  # url  expected-codes  label
  local code
  code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 15 "https://${DOMAIN}$1" || echo 000)"
  if echo "$2" | grep -qw "$code"; then
    printf '  \033[1;32m✓\033[0m %-38s %s\n' "$1" "$code"
  else
    printf '  \033[1;31m✗\033[0m %-38s %s (expected %s) — %s\n' "$1" "$code" "$2" "$3"
    return 1
  fi
}

FAILED=0
for u in / /pricing/ /partners/ /partners/apply/ /register/; do
  check "$u" "200" "public page" || FAILED=1
done
check "/api/platform-admin/stats/" "401 403" "admin API must reject anonymous" || FAILED=1

# The gate. A private document reachable by URL is a leak, not a warning.
echo
echo "  ── private document leak gate ──"
LEAK=0
for u in /media/partner_applications/ /private_media/ /media/private/; do
  check "$u" "403 404" "MUST NOT be publicly reachable" || LEAK=1
done

echo
if [ "$LEAK" -ne 0 ]; then
  die "PRIVATE DOCUMENTS ARE REACHABLE. Treat as a leak:
     1. take the site down or block the path at nginx now
     2. check access logs for hits on that path
     3. see .ai-workspace/29-deployment-report.md §3"
fi
ok "Leak gate passed"

[ "$FAILED" -eq 0 ] || die "Post-deploy checks failed — see above."

echo
echo "════════════════════════════════════════════════"
echo "  ✅ Redeploy complete: $TARGET"
echo "════════════════════════════════════════════════"
echo "  Still to confirm by eye:"
echo "    • /pricing/ shows nine plans in Arabic, «حسب العرض» on Enterprise"
echo "    • no English on an Arabic page  (proves compilemessages ran)"
echo "    • an uploaded partner document survives the next redeploy"
echo
echo "  Logs:  docker compose -f $COMPOSE_FILE logs -f $WEB"
