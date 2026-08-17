#!/usr/bin/env bash
# ============================================================================
# Tadgeeg — rehearse a migration batch on dev, against a copy of live data.
#
#   # On the dev/test server, using a backup copied over from live:
#   bash deployment/docker/rehearse_migrations.sh --from-dir /tmp/live-20260817T090000Z
#
#   # On a host that runs the source environment itself:
#   bash deployment/docker/rehearse_migrations.sh --source test
#   bash deployment/docker/rehearse_migrations.sh --keep-going
#
# TWO SERVERS
#
# live runs on one VPS and dev/test on another, so `backup.sh live` cannot be
# run on the dev host — there is no db_live container there. Take the backup on
# the live server, copy the directory across, and pass it with --from-dir:
#
#   # on live (72.62.239.220)
#   bash deployment/docker/backup.sh live
#   # then, from your workstation
#   scp -r LIVE:/path/to/deployment/docker/backups/live-<STAMP> DEV:/tmp/
#   # on dev/test (69.62.115.97)
#   bash deployment/docker/rehearse_migrations.sh --from-dir /tmp/live-<STAMP>
#
# Because the two environments are separate machines, nothing this script does
# can reach live. The shared-redis and shared-nginx caveats below apply only
# between dev and test, which do share one compose project on one host.
#
# WHY THIS EXISTS
#
# The batch waiting to deploy carries 22 migrations, seven of which add a
# UniqueConstraint to a table that already has rows, and three of which rewrite
# audit hash chains. `migrate` runs inside entrypoint.sh under `set -e`, so a
# failure there kills the container at boot, restart: unless-stopped brings it
# back to fail again, and the site is down in a crash loop.
#
# The only test that proves anything is running those migrations against real
# data. A duplicate-row query cannot: invoices/0016 fails when the backfill and
# the AddConstraint run out of order on a multi-tenant database, and no SELECT
# will tell you that in advance.
#
# WHAT IT DOES NOT TOUCH
#
# nginx is never started or rebuilt. update.sh brings up ALL services for a
# target — including nginx, which is shared with live and test — so rehearsing
# with it can interrupt the sites you are trying to protect. This script starts
# db_dev and web_dev only.
#
# redis IS shared and cannot be avoided: web_dev has
# `depends_on: redis: {condition: service_healthy}`, so compose starts it. It is
# normally already running, in which case compose leaves it alone. dev uses
# redis database 1 and live uses a different index, so the data does not mix.
#
# Data isolation is real: db_dev/mysql_dev_data and private_dev are separate
# volumes from db_live/mysql_live_data and private_live. Nothing here writes to
# live.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
BACKUP_ROOT="$SCRIPT_DIR/backups"
LOG_DIR="$SCRIPT_DIR/rehearsals"

SOURCE="live"          # environment whose data we copy (when taking it here)
FROM_DIR=""            # or: a backup directory already copied from another host
KEEP_GOING=0           # continue verification even if migrate fails

while [ $# -gt 0 ]; do
  case "$1" in
    --source)     SOURCE="${2:?--source needs live|test}"; shift ;;
    --from-dir)   FROM_DIR="${2:?--from-dir needs a path}"; shift ;;
    --keep-going) KEEP_GOING=1 ;;
    -h|--help)    sed -n '2,60p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
  shift
done

if [ -n "$FROM_DIR" ]; then
  SRC_DB=""            # nothing local to dump; the data arrived from elsewhere
  SOURCE="$(basename "$FROM_DIR" | cut -d- -f1)"
else
  case "$SOURCE" in
    live) SRC_DB=db_live ;;
    test) SRC_DB=db_test ;;
    *) echo "--source must be live or test (got '$SOURCE')" >&2; exit 1 ;;
  esac
fi

log()  { printf '\n\033[1;34m▶ %s\033[0m\n' "$1"; }
ok()   { printf '\033[1;32m  ✓ %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$1"; }
err()  { printf '\033[1;31m  ✗ %s\033[0m\n' "$1"; }
die()  { printf '\n\033[1;31m✗ REHEARSAL STOPPED: %s\033[0m\n' "$1" >&2; exit 1; }
compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

running() { compose ps --status running --services 2>/dev/null | grep -qx "$1"; }

cd "$PROJECT_ROOT"
mkdir -p "$LOG_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_LOG="$LOG_DIR/rehearsal-${STAMP}.log"

echo "╔════════════════════════════════════════════════════════╗"
echo "║  Migration rehearsal — dev, on a copy of $SOURCE data      "
echo "╚════════════════════════════════════════════════════════╝"
echo "  Source data : $SOURCE ($SRC_DB)"
echo "  Target      : dev (db_dev, web_dev)"
echo "  nginx       : NOT touched"
echo "  Log         : $RUN_LOG"
echo ""

# ── 0. Preconditions ────────────────────────────────────────────────────────
log "0/6  Checking preconditions"

[ -f "$COMPOSE_FILE" ] || die "compose file not found: $COMPOSE_FILE"
docker info >/dev/null 2>&1 || die "docker is not available to this user."

if [ -n "$FROM_DIR" ]; then
  # live and dev/test are separate VPSs, so the usual case on the dev host is a
  # backup carried over rather than taken here. Refusing early with the reason
  # beats failing inside backup.sh with "db_live is not running", which reads
  # like a broken environment rather than the wrong flag.
  [ -d "$FROM_DIR" ] || die "--from-dir path does not exist: $FROM_DIR"
  ok "using backup copied from another host: $FROM_DIR"
else
  running "$SRC_DB" || die \
    "$SRC_DB is not running on this host. If $SOURCE lives on another server, take the backup there and pass it with --from-dir."
  ok "$SRC_DB is running on this host"
fi

# How far behind is dev? Printed so the rehearsal has a stated scope.
if running web_dev; then
  PENDING="$(compose exec -T web_dev python manage.py showmigrations --plan 2>/dev/null \
             | grep -c '^\[ \]' || true)"
  ok "web_dev currently reports ${PENDING:-unknown} unapplied migration(s)"
else
  warn "web_dev is not running yet — pending count will be measured after it starts"
fi

# ── 1. Obtain the source data ───────────────────────────────────────────────
if [ -n "$FROM_DIR" ]; then
  log "1/6  Using the backup copied from the $SOURCE server"
  SRC_DIR="$FROM_DIR"
  # A directory that scp truncated restores a partial database and the whole
  # rehearsal then measures the wrong thing. Insist on seeing a dump in it.
  if ! ls "$SRC_DIR"/*.sql "$SRC_DIR"/*.sql.gz >/dev/null 2>&1; then
    die "no .sql or .sql.gz in $SRC_DIR — the copy is incomplete or the wrong directory."
  fi
  ok "backup contents look complete: $(ls -1 "$SRC_DIR" | tr '\n' ' ')"
else
  log "1/6  Backing up $SOURCE on this host (database + private_media)"
  # backup.sh verifies its own output and exits non-zero if the dump is empty or
  # truncated. Do not second-guess it; do check that it produced a directory.
  bash "$SCRIPT_DIR/backup.sh" "$SOURCE" 2>&1 | tee -a "$RUN_LOG"

  SRC_DIR="$(ls -1dt "$BACKUP_ROOT/${SOURCE}"-* 2>/dev/null | head -1 || true)"
  [ -n "$SRC_DIR" ] && [ -d "$SRC_DIR" ] || die "backup.sh produced no directory under $BACKUP_ROOT"
  ok "backup: $SRC_DIR"
fi

# ── 2. Restore it into dev ──────────────────────────────────────────────────
log "2/6  Restoring that backup into dev"

warn "This ERASES the dev database. live and test are untouched."
printf "  Type 'dev' to continue: "
read -r confirm
[ "$confirm" = "dev" ] || die "Aborted (typed '$confirm')."

# backup.sh asks for the same confirmation itself; feed it the answer we just
# collected rather than making the operator type it twice.
printf 'dev\n' | bash "$SCRIPT_DIR/backup.sh" dev --restore "$SRC_DIR" 2>&1 | tee -a "$RUN_LOG"
ok "dev now holds a copy of $SOURCE data"

# ── 3. Start ONLY db_dev and web_dev ────────────────────────────────────────
log "3/6  Building and starting db_dev + web_dev (no nginx)"

# The image runs migrate from its entrypoint. That is what we are rehearsing, so
# it is allowed to happen here — but web_dev is the only web container started,
# so nothing races it.
compose up -d --build db_dev web_dev 2>&1 | tee -a "$RUN_LOG"

printf '  waiting for web_dev '
ready=0
for _ in $(seq 1 120); do
  if compose exec -T web_dev sh -c \
      'python -c "import socket,sys; s=socket.socket(); sys.exit(s.connect_ex((\"127.0.0.1\",8000)))"' \
      >/dev/null 2>&1; then
    ready=1; printf ' ready\n'; break
  fi
  if ! running web_dev; then
    printf '\n'
    err "web_dev exited while starting — this is what a failed migration looks like."
    compose logs --tail=60 web_dev 2>&1 | tee -a "$RUN_LOG"
    die "web_dev did not survive startup. The migration batch is NOT safe to deploy."
  fi
  printf '.'; sleep 5
done
[ "$ready" -eq 1 ] || {
  compose logs --tail=60 web_dev 2>&1 | tee -a "$RUN_LOG"
  die "web_dev never became ready."
}
ok "web_dev is serving"

# ── 4. Apply migrations explicitly ──────────────────────────────────────────
log "4/6  Applying migrations"

MIGRATE_OK=1
if ! compose exec -T web_dev python manage.py migrate --noinput 2>&1 | tee -a "$RUN_LOG"; then
  MIGRATE_OK=0
  err "migrate FAILED. On a live deploy this kills the container at boot."
  [ "$KEEP_GOING" -eq 1 ] || die "See $RUN_LOG. Do not deploy this batch."
fi
[ "$MIGRATE_OK" -eq 1 ] && ok "all migrations applied"

REMAINING="$(compose exec -T web_dev python manage.py showmigrations --plan 2>/dev/null \
             | grep -c '^\[ \]' || true)"
if [ "${REMAINING:-0}" -ne 0 ]; then
  err "$REMAINING migration(s) still unapplied:"
  compose exec -T web_dev python manage.py showmigrations --plan 2>/dev/null \
    | grep '^\[ \]' | head -20 | tee -a "$RUN_LOG"
  [ "$KEEP_GOING" -eq 1 ] || die "Migration batch incomplete."
else
  ok "zero unapplied migrations"
fi

if ! compose exec -T web_dev python manage.py makemigrations --check --dry-run >/dev/null 2>&1; then
  err "model changes exist with no migration file — the mirror image of the above."
  [ "$KEEP_GOING" -eq 1 ] || die "Run makemigrations."
fi

# ── 5. Verify the hash chains, not just the absence of an error ─────────────
log "5/6  Verifying audit hash chains"

# A migration that exits 0 has not necessarily done its job. invoices/0016 warns
# that the backfill must run between AddFields and AddConstraint; if it does not,
# rows keep chain_partition="" and the chain is silently unpartitioned. Counting
# is the only way to know.
compose exec -T web_dev python manage.py shell -c "
from django.db.models import Count

def audit(label, model, partition='chain_partition', position='chain_position'):
    total = model.objects.count()
    if total == 0:
        print(f'{label:22s} rows=0  (nothing to verify)')
        return 0
    empty = model.objects.filter(**{partition: ''}).count()
    nulls = model.objects.filter(**{position + '__isnull': True}).count()
    forks = (model.objects.values(partition, position)
             .annotate(n=Count('id')).filter(n__gt=1).count())
    flag = 'FAIL' if (empty or forks) else 'ok'
    print(f'{label:22s} rows={total:<7} empty_partition={empty:<6} '
          f'null_position={nulls:<6} forks={forks:<6} {flag}')
    return 1 if (empty or forks) else 0

bad = 0
from apps.invoices.models import InvoiceAuditEvent
bad += audit('invoice_audit_event', InvoiceAuditEvent)
try:
    from apps.activity_logs.models import ActivityLog
    bad += audit('activity_log', ActivityLog)
except Exception as exc:
    print('activity_log            skipped:', exc)
try:
    from apps.authentication.models import AuditLog
    bad += audit('auth_audit_log', AuditLog)
except Exception as exc:
    print('auth_audit_log          skipped:', exc)

print()
print('CHAIN_VERDICT=' + ('FAIL' if bad else 'PASS'))
" 2>&1 | tee -a "$RUN_LOG"

if grep -q 'CHAIN_VERDICT=FAIL' "$RUN_LOG"; then
  err "A chain is unpartitioned or forked after migrating."
  err "  empty_partition > 0 means the backfill did not complete."
  err "  forks > 0 means the chain is genuinely broken."
  [ "$KEEP_GOING" -eq 1 ] || die "Do not deploy this batch."
fi
ok "chains are partitioned and fork-free"

# ── 6. Confirm the shared services never disturbed live or test ─────────────
log "6/6  Confirming live and test are still serving"

for pair in "https://tadgeeg.com/|live" "https://test.tadgeeg.com/|test"; do
  url="${pair%%|*}"; name="${pair##*|}"
  code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "$url" 2>/dev/null || echo 000)"
  case "$code" in
    200|301|302) ok "$name: $code" ;;
    000)         warn "$name: unreachable from this host (may be normal — DNS/firewall)" ;;
    *)           err "$name: $code — check whether the shared redis/nginx were disturbed" ;;
  esac
done

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  ✅ REHEARSAL PASSED                                    ║"
echo "╚════════════════════════════════════════════════════════╝"
echo "  The 22-migration batch applied cleanly to a copy of $SOURCE data,"
echo "  the audit chains are partitioned and fork-free, and dev still serves."
echo ""
echo "  Log: $RUN_LOG"
echo ""
echo "  This does NOT authorise a live deploy on its own. Before deploying:"
echo "    · take a fresh backup — update.sh only does that for target 'live',"
echo "      and 'deploy.sh update test' skips it entirely"
echo "    · deploy in an announced window, not as a routine push"
echo ""
