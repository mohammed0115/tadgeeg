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

# ── Logging ───────────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/git_sync.log"
touch "$LOG_FILE"

log() { echo "$(date '+%F %T') [$ENV_LABEL] $1" | tee -a "$LOG_FILE"; }

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
  log "📥 Repository not found — cloning fresh..."
  git clone --depth=1 -b "$BRANCH" "$REPO_URL" "$PROJECT_ROOT" >>"$LOG_FILE" 2>&1
  log "✅ Repository cloned successfully"
else
  log "📂 Repository exists — syncing origin/$BRANCH..."
  cd "$PROJECT_ROOT"

  # Ensure we're tracking the correct remote branch
  git remote set-url origin "$REPO_URL" >>"$LOG_FILE" 2>&1

  log "🔄 Fetching..."
  git fetch origin "$BRANCH" >>"$LOG_FILE" 2>&1

  log "⚠️  Hard-resetting to origin/$BRANCH (server is READ-ONLY)"
  git reset --hard "origin/$BRANCH" >>"$LOG_FILE" 2>&1
  git clean -fd >>"$LOG_FILE" 2>&1

  log "✅ Repository synced"
fi

# ── Report latest commit ──────────────────────────────────────────────────────
cd "$PROJECT_ROOT"
COMMIT=$(git log -1 --format="%h  %s  (%an, %ar)")
log "📌 HEAD: $COMMIT"

echo ""
echo "✅ [STEP 01] Git Sync PASSED for [$ENV_LABEL]"
