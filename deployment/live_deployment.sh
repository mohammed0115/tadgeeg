#!/bin/bash
# ============================================================
# FinAI — Docker-Based Live Deployment
# Usage: bash live_deployment.sh [live|dev|test]
#
# Deploys FinAI using Docker Compose.
# Each environment gets its own isolated compose stack.
# Handles: build, migrate, collectstatic, reload, healthcheck
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV="${1:-live}"

ENV_FILE="$SCRIPT_DIR/config/${ENV}.env"
[ -f "$ENV_FILE" ] || { echo "❌ Unknown environment: $ENV"; exit 1; }
source "$ENV_FILE"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/docker_deploy.log"

log()  { echo "$(date '+%F %T') [$ENV_LABEL] $1" | tee -a "$LOG_FILE"; }
fail() { log "❌ FAILED: $1"; exit 1; }

COMPOSE_FILE="$PROJECT_DIR/$DOCKER_COMPOSE_FILE"
SECRET_FILE="$WEB_ROOT/.secret.env"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  FinAI [$ENV_LABEL] — Docker Deployment                  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "  Compose file : $COMPOSE_FILE"
echo "  Project name : $DOCKER_PROJECT_NAME"
echo "  Domain       : https://$DOMAIN_MAIN"
echo ""

# ── Install Docker if not present ─────────────────────────────────────────────
install_docker() {
  if command -v docker &>/dev/null; then
    DOCKER_VER=$(docker --version | awk '{print $3}' | tr -d ',')
    log "✅ Docker already installed ($DOCKER_VER)"
    return 0
  fi

  log "📦 Installing Docker Engine..."
  apt-get update -y >>"$LOG_FILE" 2>&1
  apt-get install -y ca-certificates curl gnupg lsb-release >>"$LOG_FILE" 2>&1
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg 2>>"$LOG_FILE"
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y >>"$LOG_FILE" 2>&1
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >>"$LOG_FILE" 2>&1
  systemctl enable docker >>"$LOG_FILE" 2>&1
  systemctl start docker >>"$LOG_FILE" 2>&1
  log "✅ Docker installed"
}

# ── Generate docker-compose file for this environment ─────────────────────────
generate_compose() {
  log "📝 Generating $COMPOSE_FILE..."

  # Load secrets for env block
  SECRET_BLOCK=""
  if [ -f "$SECRET_FILE" ]; then
    while IFS= read -r line; do
      [[ "$line" =~ ^[A-Z_]+=.+ ]] && SECRET_BLOCK="${SECRET_BLOCK}      - ${line}\n" || true
    done < "$SECRET_FILE"
  fi

  cat > "$COMPOSE_FILE" <<COMPOSE
# ============================================================
# FinAI Docker Compose — $ENV_LABEL
# Generated: $(date '+%F %T')
# ============================================================

version: '3.9'

networks:
  finai_${ENV}:
    driver: bridge

volumes:
  finai_${ENV}_static:
  finai_${ENV}_media:
  finai_${ENV}_logs:

services:

  # ── Django Application ──────────────────────────────────
  web:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        - ENV=$ENV_NAME
    image: finai_${ENV}:latest
    container_name: finai_${ENV}_web
    restart: unless-stopped
    command: >
      sh -c "python manage.py migrate --noinput &&
             python manage.py collectstatic --noinput &&
             gunicorn finai_backend.wsgi:application
               --bind unix:/run/gunicorn/finai_${ENV}.sock
               --workers ${GUNICORN_WORKERS}
               --timeout ${GUNICORN_TIMEOUT}
               --max-requests ${GUNICORN_MAX_REQUESTS}
               --max-requests-jitter 50
               --log-level info
               --access-logfile /var/log/finai/access.log
               --error-logfile /var/log/finai/error.log"
    environment:
      - DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE}
      - DJANGO_ENV=${DJANGO_ENV}
      - ALLOWED_HOSTS=${ALLOWED_HOSTS}
      - REDIS_URL=${REDIS_URL}
      - DB_ENGINE=django.db.backends.mysql
      - DB_NAME=${DB_NAME}
      - DB_USER=${DB_USER}
      - DB_HOST=db
      - DB_PORT=3306
      - TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
$(printf "%b" "$SECRET_BLOCK")
    volumes:
      - finai_${ENV}_static:/app/staticfiles
      - finai_${ENV}_media:/app/media
      - finai_${ENV}_logs:/var/log/finai
      - /run/gunicorn:/run/gunicorn
    networks:
      - finai_${ENV}
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

  # ── Celery Worker ───────────────────────────────────────
  celery:
    image: finai_${ENV}:latest
    container_name: finai_${ENV}_celery
    restart: unless-stopped
    command: celery -A finai_backend worker --loglevel=info --concurrency=4
    environment:
      - DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE}
      - DJANGO_ENV=${DJANGO_ENV}
      - REDIS_URL=${REDIS_URL}
      - DB_ENGINE=django.db.backends.mysql
      - DB_NAME=${DB_NAME}
      - DB_USER=${DB_USER}
      - DB_HOST=db
      - DB_PORT=3306
$(printf "%b" "$SECRET_BLOCK")
    volumes:
      - finai_${ENV}_logs:/var/log/finai
    networks:
      - finai_${ENV}
    depends_on:
      - web
      - redis

  # ── Celery Beat ─────────────────────────────────────────
  celerybeat:
    image: finai_${ENV}:latest
    container_name: finai_${ENV}_celerybeat
    restart: unless-stopped
    command: celery -A finai_backend beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    environment:
      - DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE}
      - DJANGO_ENV=${DJANGO_ENV}
      - REDIS_URL=${REDIS_URL}
      - DB_ENGINE=django.db.backends.mysql
      - DB_NAME=${DB_NAME}
      - DB_USER=${DB_USER}
      - DB_HOST=db
      - DB_PORT=3306
$(printf "%b" "$SECRET_BLOCK")
    networks:
      - finai_${ENV}
    depends_on:
      - web
      - redis

  # ── MySQL Database ──────────────────────────────────────
  db:
    image: mysql:8.0
    container_name: finai_${ENV}_db
    restart: unless-stopped
    environment:
      - MYSQL_DATABASE=${DB_NAME}
      - MYSQL_USER=${DB_USER}
      - MYSQL_ROOT_HOST=%
$([ -f "$SECRET_FILE" ] && grep "^DB_PASSWORD=" "$SECRET_FILE" | sed 's/DB_PASSWORD=/      - MYSQL_PASSWORD=/' || echo "      # DB_PASSWORD not set — see $SECRET_FILE")
$([ -f "$SECRET_FILE" ] && grep "^DB_ROOT_PASSWORD=" "$SECRET_FILE" | sed 's/DB_ROOT_PASSWORD=/      - MYSQL_ROOT_PASSWORD=/' || echo "      # DB_ROOT_PASSWORD not set — see $SECRET_FILE")
    volumes:
      - /var/lib/mysql/finai_${ENV}:/var/lib/mysql
      - $SCRIPT_DIR/config/mysql_init_${ENV}.sql:/docker-entrypoint-initdb.d/init.sql:ro
    networks:
      - finai_${ENV}
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    command: >
      --character-set-server=utf8mb4
      --collation-server=utf8mb4_unicode_ci
      --max_allowed_packet=64M
      --innodb_buffer_pool_size=256M

  # ── Redis ───────────────────────────────────────────────
  redis:
    image: redis:7-alpine
    container_name: finai_${ENV}_redis
    restart: unless-stopped
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru --appendonly yes
    volumes:
      - /var/lib/redis/finai_${ENV}:/data
    networks:
      - finai_${ENV}
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3

  # ── Nginx (inside Docker) ───────────────────────────────
  nginx:
    image: nginx:1.25-alpine
    container_name: finai_${ENV}_nginx
    restart: unless-stopped
    ports:
      - "${PORT_GUNICORN_INTERNAL}:80"
    volumes:
      - $SCRIPT_DIR/config/nginx_${ENV}.conf:/etc/nginx/conf.d/default.conf:ro
      - finai_${ENV}_static:/app/static:ro
      - finai_${ENV}_media:/app/media:ro
      - /run/gunicorn:/run/gunicorn
    networks:
      - finai_${ENV}
    depends_on:
      - web
    healthcheck:
      test: ["CMD", "nginx", "-t"]
      interval: 30s
      timeout: 10s
      retries: 3
COMPOSE

  log "✅ Compose file generated: $COMPOSE_FILE"
}

# ── Generate MySQL init script ─────────────────────────────────────────────────
generate_mysql_init() {
  local INIT_FILE="$SCRIPT_DIR/config/mysql_init_${ENV}.sql"
  if [ -f "$INIT_FILE" ]; then
    log "✅ MySQL init script exists: $INIT_FILE"
    return 0
  fi
  cat > "$INIT_FILE" <<SQL
-- FinAI [$ENV_LABEL] MySQL Initialization
SET NAMES utf8mb4;
SET CHARACTER SET utf8mb4;
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'%';
FLUSH PRIVILEGES;
SQL
  log "✅ MySQL init script created: $INIT_FILE"
}

# ── Main deployment ────────────────────────────────────────────────────────────
DEPLOY_START=$(date +%s)

# Step 1: Docker
install_docker

# Step 2: Generate compose + init files
generate_compose
generate_mysql_init

# Step 3: Ensure data directories
log "📁 Creating persistent data directories..."
mkdir -p "/var/lib/mysql/finai_${ENV}" "/var/lib/redis/finai_${ENV}" /run/gunicorn

# Step 4: Pull base images
log "📥 Pulling latest base images..."
docker compose -f "$COMPOSE_FILE" -p "$DOCKER_PROJECT_NAME" pull --ignore-pull-failures >>"$LOG_FILE" 2>&1 || true

# Step 5: Build app image
log "🔨 Building FinAI Docker image..."
docker compose -f "$COMPOSE_FILE" -p "$DOCKER_PROJECT_NAME" build --no-cache web >>"$LOG_FILE" 2>&1

# Step 6: Start infrastructure services first (db, redis)
log "🚀 Starting database and Redis..."
docker compose -f "$COMPOSE_FILE" -p "$DOCKER_PROJECT_NAME" up -d db redis >>"$LOG_FILE" 2>&1
log "⏳ Waiting for DB to be healthy (up to 60s)..."
for i in $(seq 1 12); do
  docker compose -f "$COMPOSE_FILE" -p "$DOCKER_PROJECT_NAME" exec -T db \
    mysqladmin ping -h localhost --silent &>/dev/null && break || true
  sleep 5
done

# Step 7: Bring up application with zero-downtime (rolling update)
log "🚀 Deploying application containers..."
docker compose -f "$COMPOSE_FILE" -p "$DOCKER_PROJECT_NAME" up -d --remove-orphans >>"$LOG_FILE" 2>&1

# Step 8: Wait and verify
log "⏳ Waiting for application to be healthy..."
sleep 10

FAILED=0
for CONTAINER in \
  "finai_${ENV}_web" \
  "finai_${ENV}_celery" \
  "finai_${ENV}_redis" \
  "finai_${ENV}_db"; do

  STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || \
           docker inspect --format='{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo "unknown")

  if [[ "$STATUS" == "healthy" || "$STATUS" == "running" ]]; then
    log "  ✅ $CONTAINER: $STATUS"
  else
    log "  ❌ $CONTAINER: $STATUS"
    FAILED=$((FAILED+1))
  fi
done

[ "$FAILED" -eq 0 ] || fail "$FAILED container(s) not healthy"

# Step 9: Clean up old images
log "🧹 Cleaning up dangling images..."
docker image prune -f >>"$LOG_FILE" 2>&1 || true

DEPLOY_END=$(date +%s)
ELAPSED=$((DEPLOY_END - DEPLOY_START))

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ✅  Docker Deployment COMPLETE                          ║"
echo "╠══════════════════════════════════════════════════════════╣"
printf "║  Environment : %-43s ║\n" "$ENV_LABEL"
printf "║  Duration    : %-43s ║\n" "${ELAPSED}s"
printf "║  Compose     : %-43s ║\n" "$DOCKER_PROJECT_NAME"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Running containers:"
docker compose -f "$COMPOSE_FILE" -p "$DOCKER_PROJECT_NAME" ps
echo ""
log "🎉 Docker deployment completed in ${ELAPSED}s"
