#!/usr/bin/env bash
# ============================================================================
# Tadgeeg — backup and restore.
#
#   bash deployment/docker/backup.sh                    # backup live
#   bash deployment/docker/backup.sh dev
#   bash deployment/docker/backup.sh live --db-only
#   bash deployment/docker/backup.sh live --list
#   bash deployment/docker/backup.sh live --restore backups/live-20260801-120000
#
# Backs up TWO things, because either alone is incomplete:
#
#   1. the MySQL database
#   2. the private_media volume — partner commercial registers and
#      certificates. These are NOT in the database. A database row points at a
#      file on that volume, so restoring only MySQL gives you an application
#      that lists documents it cannot open.
#
# Every backup is verified after it is written. An unverified backup is a
# guess, and you find out it was wrong on the day you need it.
# ============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
BACKUP_ROOT="$SCRIPT_DIR/backups"

TARGET="live"
DB_ONLY=0
ACTION="backup"
RESTORE_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    live|dev|test) TARGET="$1" ;;
    --db-only)     DB_ONLY=1 ;;
    --list)        ACTION="list" ;;
    --restore)     ACTION="restore"; RESTORE_DIR="${2:-}"; shift ;;
    -h|--help)     sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
  shift
done

case "$TARGET" in
  live) DB=db_live; VOL=finai-multi-env_private_live ;;
  dev)  DB=db_dev;  VOL=finai-multi-env_private_dev ;;
  test) DB=db_test; VOL=finai-multi-env_private_test ;;
esac

ok()   { printf '\033[1;32m  ✓ %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$1"; }
die()  { printf '\n\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }
compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

# Read ONE value from an env file without sourcing it.
#
# These files contain unquoted values with spaces (SERVER_NAMES=a.com www.a.com),
# so `. file` makes the shell try to execute the second word as a command.
# `cut -d= -f2-` keeps '=' characters inside passwords intact.
env_value() {  # key file
  grep -E "^[[:space:]]*$1=" "$2" | tail -1 | cut -d= -f2- | sed 's/^["'"'"']//; s/["'"'"']$//'
}


# ── list ────────────────────────────────────────────────────────────────────
if [ "$ACTION" = "list" ]; then
  echo "Backups for $TARGET:"
  ls -1dt "$BACKUP_ROOT"/${TARGET}-* 2>/dev/null | while read -r d; do
    printf '  %-46s %s\n' "$d" "$(du -sh "$d" 2>/dev/null | cut -f1)"
  done || echo "  (none)"
  exit 0
fi

# ── restore ─────────────────────────────────────────────────────────────────
if [ "$ACTION" = "restore" ]; then
  [ -n "$RESTORE_DIR" ] || die "Usage: $0 $TARGET --restore <backup-directory>"
  [ -d "$RESTORE_DIR" ] || die "No such backup: $RESTORE_DIR"

  echo "════════════════════════════════════════════════"
  echo "  RESTORE into: $TARGET"
  echo "  From:         $RESTORE_DIR"
  echo "════════════════════════════════════════════════"
  echo
  echo "  This OVERWRITES the $TARGET database."
  printf "  Type the environment name to confirm: "
  read -r confirm
  [ "$confirm" = "$TARGET" ] || die "Aborted (typed '$confirm', expected '$TARGET')."

  if [ -f "$RESTORE_DIR/db.sql.gz" ]; then
    gzip -t "$RESTORE_DIR/db.sql.gz" || die "The dump is corrupt — refusing to restore from it."
    gunzip -c "$RESTORE_DIR/db.sql.gz" \
      | compose exec -T "$DB" sh -c 'exec mysql -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' \
      || die "Database restore failed."
    ok "Database restored"
  else
    warn "No db.sql.gz in that backup"
  fi

  if [ -f "$RESTORE_DIR/private_media.tar.gz" ]; then
    docker run --rm -v "$VOL:/restore" -v "$(cd "$RESTORE_DIR" && pwd):/backup:ro" alpine:3 \
      sh -c 'cd /restore && tar xzf /backup/private_media.tar.gz' \
      || die "private_media restore failed."
    ok "Partner documents restored"
  else
    warn "No private_media.tar.gz in that backup"
  fi

  echo
  ok "Restore complete. Restart the app: bash deployment/docker/deploy.sh $TARGET restart"
  exit 0
fi

# ── backup ──────────────────────────────────────────────────────────────────
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_ROOT/${TARGET}-${STAMP}"
mkdir -p "$DEST"

echo "════════════════════════════════════════════════"
echo "  Backup: $TARGET  →  $DEST"
echo "════════════════════════════════════════════════"

[ -f "$SCRIPT_DIR/env/${TARGET}.env" ] || die "Missing env file for $TARGET"

# 1. database
compose ps --status running --services 2>/dev/null | grep -q "^${DB}$" \
  || die "$DB is not running — start it first: bash deployment/docker/deploy.sh $TARGET up"

# --single-transaction keeps the dump consistent without locking writers out,
# which matters on live. --routines/--triggers because a schema-only dump that
# silently drops them restores into a subtly different database.
# Which engine is in there is asked of the container, not read from a settings
# file. A backup that dumps with the wrong tool fails loudly, but one that reads
# a stale DB_BACKEND and happens to find the right binary anyway teaches you
# nothing — and during a migration the two disagree by definition.
if compose exec -T "$DB" sh -c 'command -v pg_dump >/dev/null 2>&1'; then
  ENGINE=postgres
  MARKER="PostgreSQL database dump complete"
elif compose exec -T "$DB" sh -c 'command -v mysqldump >/dev/null 2>&1'; then
  ENGINE=mysql
  MARKER="Dump completed"
else
  die "$DB has neither pg_dump nor mysqldump — cannot back up."
fi
log "engine: $ENGINE"

if [ "$ENGINE" = "postgres" ]; then
  # --no-owner/--no-privileges so the dump restores under whatever role the
  # target uses; --clean --if-exists so a restore into a populated database is
  # a replacement rather than a collision.
  compose exec -T "$DB" sh -c \
    'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
       --no-owner --no-privileges --clean --if-exists' \
    | gzip > "$DEST/db.sql.gz" \
    || die "pg_dump failed — backup NOT taken."
else
  # --single-transaction keeps the dump consistent without locking writers out,
  # which matters on live. --routines/--triggers because a schema-only dump that
  # silently drops them restores into a subtly different database.
  compose exec -T "$DB" sh -c \
    'exec mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" \
       --single-transaction --quick --routines --triggers --events \
       "$MYSQL_DATABASE"' \
    | gzip > "$DEST/db.sql.gz" \
    || die "mysqldump failed — backup NOT taken."
fi

# Verify rather than assume. Both tools write a completion marker; without it
# the dump was truncated and would restore a partial database.
gzip -t "$DEST/db.sql.gz" || die "Dump is not valid gzip."
# tail -12, not -5. pg_dump 16 writes its completion marker and then a
# \unrestrict line, and a dump ending in a long FK statement can push the
# marker further back than five lines. Measured against Postgres 16.15: the
# marker sits at line 3 from the end, and mysqldump's at line 2.
gunzip -c "$DEST/db.sql.gz" | tail -12 | grep -q "$MARKER" \
  || die "Dump has no completion marker ($MARKER) — it is truncated. NOT usable."
ok "Database: $(du -h "$DEST/db.sql.gz" | cut -f1)  (verified)"

# 2. partner documents
if [ "$DB_ONLY" -eq 0 ]; then
  if docker volume inspect "$VOL" >/dev/null 2>&1; then
    docker run --rm -v "$VOL:/data:ro" -v "$DEST:/backup" alpine:3 \
      sh -c 'tar czf /backup/private_media.tar.gz -C /data .' \
      || die "private_media backup failed."
    gzip -t "$DEST/private_media.tar.gz" || die "Document archive is corrupt."
    COUNT="$(docker run --rm -v "$DEST:/backup:ro" alpine:3 sh -c 'tar tzf /backup/private_media.tar.gz | grep -vc "/$"' || echo 0)"
    ok "Partner documents: $(du -h "$DEST/private_media.tar.gz" | cut -f1), ${COUNT} file(s)  (verified)"
  else
    warn "Volume $VOL does not exist yet — no documents to back up"
  fi
else
  warn "--db-only: partner documents NOT backed up"
fi

# 3. what this was taken from, so a restore is not guesswork later
{
  echo "environment : $TARGET"
  echo "taken_at    : $(date -Is)"
  echo "git_commit  : $(git -C "$SCRIPT_DIR/../.." rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "git_subject : $(git -C "$SCRIPT_DIR/../.." log -1 --pretty=%s 2>/dev/null || echo unknown)"
  echo "db_name     : $(env_value MYSQL_DATABASE "$SCRIPT_DIR/env/${TARGET}.env")"
} > "$DEST/MANIFEST.txt"
ok "Manifest written"

echo
echo "════════════════════════════════════════════════"
echo "  ✅ Backup complete"
echo "════════════════════════════════════════════════"
echo "  $DEST"
echo
echo "  Restore:  bash deployment/docker/backup.sh $TARGET --restore $DEST"
echo "  List:     bash deployment/docker/backup.sh $TARGET --list"
echo
echo "  Copy it off this machine. A backup on the same server as the"
echo "  database is not a backup — it dies with the disk:"
echo "    scp -r root@72.62.239.220:$DEST ./"
