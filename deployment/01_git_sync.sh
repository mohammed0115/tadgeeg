#!/bin/bash
# ============================================================
# FinAI Deployment — Step 01: Git Sync
# Usage: bash 01_git_sync.sh [live|dev|test]
# Smart: clones if missing, updates (reset --hard) if exists
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV="${1:-live}"

ENV_FILE="$SCRIPT_DIR/config/${ENV}.env"
[ -f "$ENV_FILE" ] || { echo "❌ Unknown environment: $ENV"; exit 1; }
source "$ENV_FILE"
SYNC_REPO_URL="${SYNC_REPO_URL:-$REPO_URL}"

# ── Logging ───────────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/git_sync.log"
touch "$LOG_FILE"

log() { echo "$(date '+%F %T') [$ENV_LABEL] $1" | tee -a "$LOG_FILE"; }

project_root_has_contents() {
  [ -d "$PROJECT_ROOT" ] && find "$PROJECT_ROOT" -mindepth 1 -maxdepth 1 -print -quit | grep -q .
}

clean_untracked() {
  git clean -fd \
    -e ".secret.env" \
    -e ".env" \
    -e "deployment/docker/env/*.env" \
    -e "venv/" \
    -e ".venv/" >>"$LOG_FILE" 2>&1
}

bootstrap_repo_in_place() {
  mkdir -p "$PROJECT_ROOT"
  cd "$PROJECT_ROOT"

  git init >>"$LOG_FILE" 2>&1

  if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "$SYNC_REPO_URL" >>"$LOG_FILE" 2>&1
  else
    git remote add origin "$SYNC_REPO_URL" >>"$LOG_FILE" 2>&1
  fi

  log "🔄 Fetching..."
  git fetch --depth=1 origin "$BRANCH" >>"$LOG_FILE" 2>&1
  git checkout -f -B "$BRANCH" FETCH_HEAD >>"$LOG_FILE" 2>&1
}

# ── Lock (prevent concurrent sync) ───────────────────────────────────────────
LOCK_FILE="/var/lock/finai_git_${ENV}.lock"
exec 200>"$LOCK_FILE"
flock -n 200 || { log "⏳ Another git sync is already running. Exiting."; exit 0; }

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  FinAI [$ENV_LABEL] — STEP 01: Git Sync     ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

log "Branch: $BRANCH  →  $PROJECT_ROOT"

# ── Ensure parent directory exists ───────────────────────────────────────────
mkdir -p "$(dirname "$PROJECT_ROOT")"

# ── Clone or update ───────────────────────────────────────────────────────────
if [ ! -d "$PROJECT_ROOT/.git" ]; then
  if project_root_has_contents; then
    log "📁 Project root is not empty — bootstrapping Git in place..."
    bootstrap_repo_in_place
    log "✅ Repository initialized successfully"
  else
    log "📥 Repository not found — cloning fresh..."
    git clone --depth=1 -b "$BRANCH" "$SYNC_REPO_URL" "$PROJECT_ROOT" >>"$LOG_FILE" 2>&1
    log "✅ Repository cloned successfully"
  fi
else
  log "📂 Repository exists — syncing origin/$BRANCH..."
  cd "$PROJECT_ROOT"

  # Ensure we're tracking the correct remote branch
  git remote set-url origin "$SYNC_REPO_URL" >>"$LOG_FILE" 2>&1

  log "🔄 Fetching..."
  git fetch origin "$BRANCH" >>"$LOG_FILE" 2>&1

  log "⚠️  Hard-resetting to origin/$BRANCH (server is READ-ONLY)"
  git reset --hard "origin/$BRANCH" >>"$LOG_FILE" 2>&1
  clean_untracked

  log "✅ Repository synced"
fi

# ── Report latest commit ──────────────────────────────────────────────────────
cd "$PROJECT_ROOT"
COMMIT=$(git log -1 --format="%h  %s  (%an, %ar)")
log "📌 HEAD: $COMMIT"

echo ""
echo "✅ [STEP 01] Git Sync PASSED for [$ENV_LABEL]"
