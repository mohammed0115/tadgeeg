#!/bin/bash
# ============================================================
# FinAI Deployment — Step 06: SSL/TLS Setup (Let's Encrypt)
# Usage: bash 06_ssl_setup.sh [live|dev|test]
# Smart: renews if cert exists, issues new if missing
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV="${1:-live}"

ENV_FILE="$SCRIPT_DIR/config/${ENV}.env"
[ -f "$ENV_FILE" ] || { echo "❌ Unknown environment: $ENV"; exit 1; }
source "$ENV_FILE"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/ssl_setup.log"

log() { echo "$(date '+%F %T') [$ENV_LABEL] $1" | tee -a "$LOG_FILE"; }

echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║  FinAI [$ENV_LABEL] — STEP 06: SSL/TLS Setup     ║"
echo "╚═══════════════════════════════════════════════════╝"
echo ""

# ── SSL disabled check ────────────────────────────────────────────────────────
if [ "${USE_SSL:-true}" != "true" ]; then
  log "ℹ️  USE_SSL=false — skipping SSL setup"
  echo "✅ [STEP 06] SSL skipped (USE_SSL=false)"
  exit 0
fi

# ── Certbot install ───────────────────────────────────────────────────────────
if command -v certbot &>/dev/null; then
  CERTBOT_VER=$(certbot --version 2>&1 | awk '{print $2}')
  log "✅ Certbot already installed ($CERTBOT_VER)"
else
  log "📦 Installing Certbot..."
  apt-get update -y >>"$LOG_FILE" 2>&1
  apt-get install -y certbot python3-certbot-nginx >>"$LOG_FILE" 2>&1
  log "✅ Certbot installed"
fi

# ── DNS check ─────────────────────────────────────────────────────────────────
log "🔍 Checking DNS resolution for $DOMAIN_MAIN..."
RESOLVED_IP=$(dig +short "$DOMAIN_MAIN" | tail -1 2>/dev/null || host "$DOMAIN_MAIN" | awk '/has address/{print $4}' | head -1 || echo "")

if [ "$RESOLVED_IP" = "$SERVER_IP" ]; then
  log "✅ DNS OK: $DOMAIN_MAIN → $RESOLVED_IP"
elif [ -z "$RESOLVED_IP" ]; then
  log "⚠️  DNS not resolving yet for $DOMAIN_MAIN — SSL issuance may fail"
else
  log "⚠️  DNS resolves to $RESOLVED_IP (expected $SERVER_IP) — continuing anyway"
fi

# ── Nginx config test ─────────────────────────────────────────────────────────
log "🔍 Testing Nginx before SSL issuance..."
nginx -t >>"$LOG_FILE" 2>&1 || { log "❌ Nginx config invalid — fix before SSL"; exit 1; }

# ── Build domain arguments ────────────────────────────────────────────────────
DOMAIN_ARGS=""
for DOMAIN in $DOMAIN_ALL; do
  DOMAIN_ARGS="$DOMAIN_ARGS -d $DOMAIN"
done

# ── Check if certificate already exists and is valid ─────────────────────────
CERT_PATH="/etc/letsencrypt/live/$DOMAIN_MAIN/fullchain.pem"

if [ -f "$CERT_PATH" ]; then
  # Certificate exists — check expiry
  EXPIRY=$(openssl x509 -enddate -noout -in "$CERT_PATH" 2>/dev/null | cut -d= -f2 || echo "")
  EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s 2>/dev/null || echo "0")
  NOW_EPOCH=$(date +%s)
  DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))

  log "📜 Existing certificate expires in $DAYS_LEFT days ($EXPIRY)"

  if [ "$DAYS_LEFT" -gt 30 ]; then
    log "✅ Certificate is valid ($DAYS_LEFT days left) — no renewal needed"
  else
    log "🔁 Certificate expires soon — renewing..."
    certbot renew \
      --nginx \
      --non-interactive \
      --quiet \
      >> "$LOG_FILE" 2>&1
    log "✅ Certificate renewed"
  fi
else
  # No certificate — issue new one
  log "📜 Requesting new SSL certificate from Let's Encrypt..."
  certbot --nginx \
    $DOMAIN_ARGS \
    --email "$SSL_EMAIL" \
    --agree-tos \
    --no-eff-email \
    --redirect \
    --non-interactive \
    >> "$LOG_FILE" 2>&1
  log "✅ SSL certificate issued"
fi

# ── Setup auto-renewal cron ───────────────────────────────────────────────────
CRON_ENTRY="0 3 * * * certbot renew --quiet --post-hook 'systemctl reload nginx'"
CRON_FILE="/etc/cron.d/certbot_finai_${ENV}"

if [ -f "$CRON_FILE" ]; then
  log "✅ Auto-renewal cron already configured: $CRON_FILE"
else
  echo "$CRON_ENTRY" > "$CRON_FILE"
  chmod 644 "$CRON_FILE"
  log "🔁 Auto-renewal cron created: $CRON_FILE"
fi

# ── Dry-run test ──────────────────────────────────────────────────────────────
log "🔁 Testing auto-renewal (dry-run)..."
certbot renew --dry-run --quiet >>"$LOG_FILE" 2>&1 && log "✅ Dry-run OK" || log "⚠️  Dry-run had warnings (check certbot logs)"

# ── Reload Nginx ──────────────────────────────────────────────────────────────
systemctl reload nginx >>"$LOG_FILE" 2>&1

echo ""
echo "✅ [STEP 06] SSL Setup COMPLETED for [$ENV_LABEL]"
echo "   🔒 https://$DOMAIN_MAIN"
[ -n "$DOMAIN_WWW" ] && echo "   🔒 https://$DOMAIN_WWW" || true
