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

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/nginx_setup.log"

log() { echo "$(date '+%F %T') [$ENV_LABEL] $1" | tee -a "$LOG_FILE"; }

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  FinAI [$ENV_LABEL] — STEP 05: Nginx Configuration  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Pre-flight ────────────────────────────────────────────────────────────────
command -v nginx &>/dev/null || { log "❌ Nginx not installed. Run 02_system_setup.sh first."; exit 1; }

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

cat > "$NGINX_SITE_FILE" <<NGINX
# ============================================================
# FinAI — Nginx Site Config: $ENV_LABEL
# Domains: $DOMAIN_ALL
# Generated: $(date '+%F %T')
# ============================================================

# Rate limiting zones
limit_req_zone \$binary_remote_addr zone=finai_${ENV}_api:10m rate=30r/m;
limit_req_zone \$binary_remote_addr zone=finai_${ENV}_upload:10m rate=10r/m;

# Upstream
upstream finai_${ENV}_gunicorn {
    server unix:${SOCKET} fail_timeout=10s;
}

# ── HTTP → HTTPS redirect ──────────────────────────────────
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN_ALL;

    # ACME challenge (Let's Encrypt)
    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

# ── HTTPS ──────────────────────────────────────────────────
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name $DOMAIN_ALL;

    # SSL (certbot will fill in certificate paths)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_stapling on;
    ssl_stapling_verify on;

    # HSTS (only set on live)
$([ "$ENV_NAME" = "live" ] && echo '    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;' || echo '    # HSTS disabled on non-live environments')

    # Size limits
    client_max_body_size 50M;
    client_body_timeout 60s;
    client_header_timeout 60s;
    keepalive_timeout 65s;
    send_timeout 60s;

    # Logs
    access_log /var/log/nginx/finai_${ENV}_access.log combined;
    error_log  /var/log/nginx/finai_${ENV}_error.log warn;

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
        # Block direct access to uploaded documents
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
}
NGINX

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
echo "   Domain:  https://$DOMAIN_MAIN"
