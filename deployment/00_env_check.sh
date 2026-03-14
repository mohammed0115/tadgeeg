#!/bin/bash
# ============================================================
# FinAI Deployment — Step 00: Environment Check
# Usage: bash 00_env_check.sh [live|dev|test]
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV="${1:-live}"

# ── Load env config ───────────────────────────────────────────────────────────
ENV_FILE="$SCRIPT_DIR/config/${ENV}.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "❌ Unknown environment: '$ENV'  (expected: live | dev | test)"
  exit 1
fi
source "$ENV_FILE"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  FinAI [$ENV_LABEL] — STEP 00: Environment Check ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

PASS=0
FAIL=0

check() {
  local label="$1"
  local ok="$2"
  local hint="${3:-}"
  if [ "$ok" = "true" ]; then
    echo "  ✅ $label"
    PASS=$((PASS+1))
  else
    echo "  ❌ $label${hint:+  — $hint}"
    FAIL=$((FAIL+1))
  fi
}

# ── 1. OS ─────────────────────────────────────────────────────────────────────
if grep -qi ubuntu /etc/os-release 2>/dev/null; then
  OS_VER=$(grep VERSION_ID /etc/os-release | cut -d'"' -f2)
  check "Ubuntu OS (version $OS_VER)" "true"
else
  check "Ubuntu OS" "false" "Non-Ubuntu systems are not supported"
fi

# ── 2. Root ───────────────────────────────────────────────────────────────────
[ "$EUID" -eq 0 ] && check "Running as root" "true" \
                  || check "Running as root" "false" "Re-run with sudo or as root"

# ── 3. Disk space (>= 10 GB) ─────────────────────────────────────────────────
FREE_KB=$(df / | tail -1 | awk '{print $4}')
FREE_GB=$(echo "scale=1; $FREE_KB/1048576" | bc 2>/dev/null || echo "?")
[ "$FREE_KB" -ge 10485760 ] \
  && check "Disk space (${FREE_GB}GB free)" "true" \
  || check "Disk space (${FREE_GB}GB free)" "false" "Need at least 10 GB"

# ── 4. RAM (>= 2 GB) ─────────────────────────────────────────────────────────
MEM_MB=$(free -m | awk '/Mem:/{print $2}')
[ "$MEM_MB" -ge 2000 ] \
  && check "RAM (${MEM_MB}MB)" "true" \
  || check "RAM (${MEM_MB}MB)" "false" "Need at least 2 GB RAM"

# ── 5. Internet ───────────────────────────────────────────────────────────────
ping -c1 -W3 8.8.8.8 &>/dev/null \
  && check "Internet connectivity" "true" \
  || check "Internet connectivity" "false" "No network access"

# ── 6. Python 3.12 ───────────────────────────────────────────────────────────
if command -v python3.12 &>/dev/null; then
  PY_VER=$(python3.12 --version 2>&1 | awk '{print $2}')
  check "Python 3.12 ($PY_VER)" "true"
else
  echo "  ⚠️  Python 3.12 not installed yet — will be installed in Step 02"
fi

# ── 7. Git ────────────────────────────────────────────────────────────────────
if command -v git &>/dev/null; then
  GIT_VER=$(git --version | awk '{print $3}')
  check "Git ($GIT_VER)" "true"
else
  echo "  ⚠️  Git not installed yet — will be installed in Step 02"
fi

# ── 8. MySQL client ──────────────────────────────────────────────────────────
command -v mysql &>/dev/null \
  && check "MySQL client" "true" \
  || echo "  ⚠️  MySQL client not found — will be installed in Step 02"

# ── 9. Nginx ─────────────────────────────────────────────────────────────────
command -v nginx &>/dev/null \
  && check "Nginx" "true" \
  || echo "  ⚠️  Nginx not installed yet — will be installed in Step 02"

# ── 10. WEB_ROOT directory ───────────────────────────────────────────────────
[ -d "$WEB_ROOT" ] \
  && check "Web root exists ($WEB_ROOT)" "true" \
  || echo "  ⚠️  $WEB_ROOT not found — will be created in Step 04"

# ── 11. Firewall ports ────────────────────────────────────────────────────────
for PORT in 80 443; do
  if ss -tlnp | grep -q ":$PORT "; then
    check "Port $PORT is in use (OK — Nginx will own it)" "true"
  else
    echo "  ℹ️  Port $PORT is free (Nginx will bind it)"
  fi
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "  ─────────────────────────────────────────────────"
echo "  Checks passed: $PASS  |  Failed: $FAIL"
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo "❌ [STEP 00] Environment check FAILED — fix the issues above before continuing."
  exit 1
fi

echo "✅ [STEP 00] Environment check PASSED for [$ENV_LABEL]"
