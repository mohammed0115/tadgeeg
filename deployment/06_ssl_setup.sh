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

APT_RETRY_COUNT="${APT_RETRY_COUNT:-3}"

run_with_retries() {
  local description="$1"
  shift
  local attempt=1

  until "$@" >>"$LOG_FILE" 2>&1; do
    if [ "$attempt" -ge "$APT_RETRY_COUNT" ]; then
      log "❌ ${description} failed after ${APT_RETRY_COUNT} attempts"
      return 1
    fi

    log "⚠️  ${description} failed (attempt ${attempt}/${APT_RETRY_COUNT}) — retrying in 5 seconds..."
    attempt=$((attempt + 1))
    sleep 5
  done

  return 0
}

apt_update() {
  run_with_retries "apt-get update" apt-get update -y
}

apt_install() {
  [ "$#" -gt 0 ] || return 0
  run_with_retries "apt-get install: $*" apt-get install -y "$@"
}

ensure_nginx_and_certbot() {
  if ! command -v nginx &>/dev/null; then
    log "📦 Nginx not installed — installing automatically before SSL setup"
    apt_update
    apt_install nginx ca-certificates
  fi

  if command -v certbot &>/dev/null; then
    CERTBOT_VER=$(certbot --version 2>&1 | awk '{print $2}')
    log "✅ Certbot already installed ($CERTBOT_VER)"
  else
    log "📦 Installing Certbot..."
    apt_update
    apt_install certbot python3-certbot-nginx
    log "✅ Certbot installed"
  fi

  systemctl enable nginx >>"$LOG_FILE" 2>&1 || true
  systemctl start nginx >>"$LOG_FILE" 2>&1 || systemctl restart nginx >>"$LOG_FILE" 2>&1 || true
}

resolve_domain_ip() {
  local domain="$1"

  getent ahostsv4 "$domain" 2>/dev/null | awk 'NR==1 {print $1; exit}' \
    || dig +short "$domain" 2>/dev/null | tail -1 \
    || host "$domain" 2>/dev/null | awk '/has address/{print $4}' | head -1 \
    || true
}

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

ensure_nginx_and_certbot

mkdir -p /var/www/letsencrypt

if [ ! -f "$NGINX_SITE_FILE" ]; then
  log "ℹ️  Nginx site config not found yet — generating it before SSL setup"
  bash "$SCRIPT_DIR/05_nginx_setup.sh" "$ENV" >>"$LOG_FILE" 2>&1 || {
    log "❌ Failed to generate Nginx site config before SSL setup"
    exit 1
  }
fi

# ── DNS check ─────────────────────────────────────────────────────────────────
log "🔍 Checking DNS resolution for $DOMAIN_MAIN..."
RESOLVED_IP="$(resolve_domain_ip "$DOMAIN_MAIN")"
DNS_READY="false"

if [ "$RESOLVED_IP" = "$SERVER_IP" ]; then
  DNS_READY="true"
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
      --non-interactive \
      --quiet \
      >> "$LOG_FILE" 2>&1 \
      && log "✅ Certificate renewed" \
      || log "⚠️  Certificate renewal returned warnings — check certbot output"
  fi
else
  if [ "$DNS_READY" != "true" ]; then
    if [ "$ENV_NAME" = "live" ]; then
      log "❌ DNS for $DOMAIN_MAIN must point to $SERVER_IP before live SSL can be issued"
      exit 1
    fi

    log "⚠️  DNS is not ready for $DOMAIN_MAIN — skipping SSL issuance and keeping HTTP-only Nginx config"
    echo ""
    echo "⚠️  [STEP 06] SSL skipped for [$ENV_LABEL] until DNS points to $SERVER_IP"
    exit 0
  fi

  log "📜 Requesting new SSL certificate from Let's Encrypt (webroot validation)..."
  certbot certonly \
    --webroot \
    --webroot-path /var/www/letsencrypt \
    $DOMAIN_ARGS \
    --email "$SSL_EMAIL" \
    --agree-tos \
    --no-eff-email \
    --non-interactive \
    >> "$LOG_FILE" 2>&1
  log "✅ SSL certificate issued"
fi

if [ -f "$CERT_PATH" ]; then
  log "🔁 Rebuilding Nginx config with SSL certificates..."
  bash "$SCRIPT_DIR/05_nginx_setup.sh" "$ENV" >>"$LOG_FILE" 2>&1 || {
    log "❌ Failed to rebuild Nginx config after SSL issuance/renewal"
    exit 1
  }
fi

# ── Setup auto-renewal cron ───────────────────────────────────────────────────
CRON_ENTRY="0 3 * * * root certbot renew --quiet --post-hook 'systemctl reload nginx'"
CRON_FILE="/etc/cron.d/certbot_finai_${ENV}"

if [ -f "$CRON_FILE" ]; then
  log "✅ Auto-renewal cron already configured: $CRON_FILE"
else
  echo "$CRON_ENTRY" > "$CRON_FILE"
  chmod 644 "$CRON_FILE"
  log "🔁 Auto-renewal cron created: $CRON_FILE"
fi

# ── Dry-run test ──────────────────────────────────────────────────────────────
if [ -f "$CERT_PATH" ]; then
  log "🔁 Testing auto-renewal (dry-run)..."
  certbot renew --dry-run --quiet >>"$LOG_FILE" 2>&1 && log "✅ Dry-run OK" || log "⚠️  Dry-run had warnings (check certbot logs)"
else
  log "ℹ️  No certificate exists yet — skipping certbot dry-run"
fi

# ── Reload Nginx ──────────────────────────────────────────────────────────────
systemctl reload nginx >>"$LOG_FILE" 2>&1 || systemctl restart nginx >>"$LOG_FILE" 2>&1

echo ""
echo "✅ [STEP 06] SSL Setup COMPLETED for [$ENV_LABEL]"
echo "   🔒 https://$DOMAIN_MAIN"
[ -n "$DOMAIN_WWW" ] && echo "   🔒 https://$DOMAIN_WWW" || true
