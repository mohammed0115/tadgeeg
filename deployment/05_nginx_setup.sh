#!/bin/bash
# ============================================================
# FinAI Deployment — Step 05: Nginx Setup
# Usage: bash 05_nginx_setup.sh [live|dev|test]
# Smart: updates site config if exists, creates if not
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV="${1:-live}"

ENV_FILE="$SCRIPT_DIR/config/${ENV}.env"
[ -f "$ENV_FILE" ] || { echo "❌ Unknown environment: $ENV"; exit 1; }
source "$ENV_FILE"
export DEBIAN_FRONTEND=noninteractive

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/nginx_setup.log"

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

ensure_nginx_available() {
  if command -v nginx &>/dev/null; then
    local nginx_version
    nginx_version="$(nginx -v 2>&1 | awk -F/ '{print $2}')"
    log "✅ Nginx already installed (${nginx_version:-unknown})"
  else
    log "📦 Nginx not installed — installing automatically..."
    apt_update
    apt_install nginx ca-certificates
    log "✅ Nginx installed"
  fi

  systemctl enable nginx >>"$LOG_FILE" 2>&1 || true
  systemctl start nginx >>"$LOG_FILE" 2>&1 || systemctl restart nginx >>"$LOG_FILE" 2>&1 || true
}

write_application_locations() {
  cat <<NGINX
    # ── Static files ─────────────────────────────────────
    location /static/ {
        alias $STATIC_ROOT/;
        expires 30d;
        access_log off;
        add_header Cache-Control "public, immutable";
        gzip_static on;
    }

    # ── Media files ──────────────────────────────────────
    location /media/ {
        alias $MEDIA_ROOT/;
        expires 7d;
        add_header Cache-Control "private";
        location ~* \.(pdf|docx?|xlsx?|zip)$ {
            add_header Content-Disposition "attachment";
        }
    }

    # ── API endpoints (rate-limited) ─────────────────────
    location /api/v1/documents/upload {
        limit_req zone=finai_${ENV}_upload burst=5 nodelay;
        limit_req_status 429;
        include proxy_params;
        proxy_pass http://finai_${ENV}_gunicorn;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    location /api/ {
        limit_req zone=finai_${ENV}_api burst=20 nodelay;
        limit_req_status 429;
        include proxy_params;
        proxy_pass http://finai_${ENV}_gunicorn;
        proxy_read_timeout 120s;
    }

    # ── WebSocket (Django Channels) ───────────────────────
    location /ws/ {
        proxy_pass http://finai_${ENV}_gunicorn;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
    }

    # ── Health check ──────────────────────────────────────
    location /health/ {
        include proxy_params;
        proxy_pass http://finai_${ENV}_gunicorn;
        access_log off;
    }

    # ── Django / Gunicorn (catch-all) ────────────────────
    location / {
        include proxy_params;
        proxy_pass http://finai_${ENV}_gunicorn;
        proxy_read_timeout 120s;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # ── Deny hidden files ─────────────────────────────────
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }
NGINX
}

write_http_server() {
  if [ "${USE_SSL:-true}" = "true" ] && [ "$SSL_READY" = "true" ]; then
    cat <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN_ALL;

    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}
NGINX
  else
    cat <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN_ALL;

    access_log /var/log/nginx/finai_${ENV}_access.log combined;
    error_log  /var/log/nginx/finai_${ENV}_error.log warn;

    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }

$(write_application_locations)
}
NGINX
  fi
}

write_https_server() {
  [ "${USE_SSL:-true}" = "true" ] || return 0
  [ "$SSL_READY" = "true" ] || return 0

  cat <<NGINX

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name $DOMAIN_ALL;

    ssl_certificate $CERT_FULLCHAIN;
    ssl_certificate_key $CERT_PRIVKEY;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_stapling on;
    ssl_stapling_verify on;

$([ "$ENV_NAME" = "live" ] && echo '    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;' || echo '    # HSTS disabled on non-live environments')

    client_max_body_size 50M;
    client_body_timeout 60s;
    client_header_timeout 60s;
    keepalive_timeout 65s;
    send_timeout 60s;

    access_log /var/log/nginx/finai_${ENV}_access.log combined;
    error_log  /var/log/nginx/finai_${ENV}_error.log warn;

$(write_application_locations)
}
NGINX
}

write_nginx_site() {
  cat <<NGINX
# ============================================================
# FinAI — Nginx Site Config: $ENV_LABEL
# Domains: $DOMAIN_ALL
# Generated: $(date '+%F %T')
# ============================================================

limit_req_zone \$binary_remote_addr zone=finai_${ENV}_api:10m rate=30r/m;
limit_req_zone \$binary_remote_addr zone=finai_${ENV}_upload:10m rate=10r/m;

upstream finai_${ENV}_gunicorn {
    server unix:${NGINX_SOCKET} fail_timeout=10s;
}
NGINX

  write_http_server
  write_https_server
}

resolve_socket_path() {
  local configured_socket="$1"
  local configured_dir
  configured_dir="$(dirname "$configured_socket")"

  if [ "$configured_dir" = "/run" ]; then
    echo "/run/${SERVICE_NAME}/$(basename "$configured_socket")"
  else
    echo "$configured_socket"
  fi
}

NGINX_SOCKET="$(resolve_socket_path "$SOCKET")"
CERT_FULLCHAIN="/etc/letsencrypt/live/$DOMAIN_MAIN/fullchain.pem"
CERT_PRIVKEY="/etc/letsencrypt/live/$DOMAIN_MAIN/privkey.pem"
SSL_READY="false"

if [ "${USE_SSL:-true}" = "true" ] && [ -f "$CERT_FULLCHAIN" ] && [ -f "$CERT_PRIVKEY" ]; then
  SSL_READY="true"
fi

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  FinAI [$ENV_LABEL] — STEP 05: Nginx Configuration  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Pre-flight ────────────────────────────────────────────────────────────────
ensure_nginx_available

if [ "${USE_SSL:-true}" = "true" ] && [ "$SSL_READY" != "true" ]; then
  log "ℹ️  SSL certificate not found yet for $DOMAIN_MAIN — writing HTTP-only config until Step 06 succeeds"
fi

# Socket may not exist yet if gunicorn hasn't started; we write config anyway
# and let it be validated after gunicorn is running.

# ── Write nginx.conf security baseline (global, only once) ───────────────────
NGINX_CONF="/etc/nginx/nginx.conf"
if ! grep -q "finai_security" "$NGINX_CONF" 2>/dev/null; then
  log "🔧 Hardening global nginx.conf..."
  # Inject security header block in http block
  sed -i '/http {/a \
    # --- FinAI Security Baseline ---\n\
    server_tokens off;\n\
    add_header X-Frame-Options SAMEORIGIN;\n\
    add_header X-Content-Type-Options nosniff;\n\
    add_header X-XSS-Protection "1; mode=block";\n\
    add_header Referrer-Policy "strict-origin-when-cross-origin";\n\
    # finai_security\n' "$NGINX_CONF" 2>/dev/null || true
fi

# ── Write site config ─────────────────────────────────────────────────────────
log "📝 Writing Nginx site: $NGINX_SITE_FILE"

mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled

write_nginx_site > "$NGINX_SITE_FILE"

# ── Enable site ───────────────────────────────────────────────────────────────
log "🔗 Enabling site..."
ln -sf "$NGINX_SITE_FILE" "$NGINX_ENABLED_FILE"

# ── Create ACME challenge root ────────────────────────────────────────────────
mkdir -p /var/www/letsencrypt

# ── Remove default nginx site (only on first deployment) ──────────────────────
if [ -f /etc/nginx/sites-enabled/default ]; then
  rm -f /etc/nginx/sites-enabled/default
  log "🗑️  Removed default nginx site"
fi

# ── Test config ───────────────────────────────────────────────────────────────
log "🔍 Testing nginx configuration..."
nginx -t >>"$LOG_FILE" 2>&1 || {
  log "❌ Nginx config test FAILED — check $NGINX_SITE_FILE"
  nginx -t
  exit 1
}
log "✅ Nginx config OK"

# ── Reload ────────────────────────────────────────────────────────────────────
log "🔄 Reloading Nginx..."
systemctl enable nginx >>"$LOG_FILE" 2>&1
systemctl reload nginx >>"$LOG_FILE" 2>&1 || systemctl restart nginx >>"$LOG_FILE" 2>&1

systemctl is-active --quiet nginx \
  && log "✅ Nginx is running" \
  || { log "❌ Nginx failed to start"; exit 1; }

echo ""
echo "✅ [STEP 05] Nginx Setup COMPLETED for [$ENV_LABEL]"
if [ "$SSL_READY" = "true" ]; then
  echo "   Domain:  https://$DOMAIN_MAIN"
else
  echo "   Domain:  http://$DOMAIN_MAIN"
fi
