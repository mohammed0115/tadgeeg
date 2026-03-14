#!/bin/bash
# ============================================================
# FinAI — Server Setup & Environment Config Generator
# Usage: bash setup_server.sh
#
# What this script does:
#   1. Asks for GitHub repo URL and token
#   2. Clones the project to /root/finai-deploy
#   3. Interactively collects values for each environment
#   4. Writes deployment/config/live.env, dev.env, test.env
#   5. Optionally creates .secret.env files on the server
#   6. Makes all deployment scripts executable
# ============================================================
set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $1"; }
success() { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()     { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
ask()     { echo -e "${BOLD}$1${NC}"; }

# ── Header ────────────────────────────────────────────────────────────────────
clear
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   FinAI — Server Setup & Config Generator                ║"
echo "║   Generates: live.env · dev.env · test.env               ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Root check ────────────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
  warn "Not running as root. Some steps (mkdir /var/www, etc.) may fail."
  warn "Run as root or with sudo for a full server setup."
  echo ""
fi

# ── Step 1: GitHub repository ─────────────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 1 — GitHub Repository"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ask "GitHub repository URL (e.g. https://github.com/mohammed0115/tadgeeg.git):"
read -r REPO_URL
REPO_URL="${REPO_URL:-https://github.com/mohammed0115/tadgeeg.git}"

ask "GitHub Personal Access Token (leave blank to use SSH / public repo):"
read -rs GITHUB_TOKEN
echo ""

# Build authenticated URL if token is provided
if [ -n "$GITHUB_TOKEN" ]; then
  # Insert token into URL: https://TOKEN@github.com/...
  CLONE_URL="${REPO_URL/https:\/\//https://${GITHUB_TOKEN}@}"
else
  CLONE_URL="$REPO_URL"
fi

ask "Destination directory on this server [/root/finai-deploy]:"
read -r DEPLOY_DIR
DEPLOY_DIR="${DEPLOY_DIR:-/root/finai-deploy}"

# ── Clone or update ───────────────────────────────────────────────────────────
echo ""
if [ -d "$DEPLOY_DIR/.git" ]; then
  info "Repository already exists at $DEPLOY_DIR — pulling latest changes..."
  git -C "$DEPLOY_DIR" remote set-url origin "$CLONE_URL" 2>/dev/null || true
  git -C "$DEPLOY_DIR" fetch origin --quiet
  git -C "$DEPLOY_DIR" reset --hard origin/main 2>/dev/null \
    || git -C "$DEPLOY_DIR" reset --hard origin/master 2>/dev/null \
    || warn "Could not reset to origin/main or origin/master"
  success "Repository updated at $DEPLOY_DIR"
else
  info "Cloning repository to $DEPLOY_DIR ..."
  git clone "$CLONE_URL" "$DEPLOY_DIR" || err "Clone failed. Check the URL and token."
  success "Repository cloned to $DEPLOY_DIR"
fi

SCRIPT_DIR="$DEPLOY_DIR/deployment"
CONFIG_DIR="$SCRIPT_DIR/config"
mkdir -p "$CONFIG_DIR"

# Make all deployment scripts executable
chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true
success "All deployment scripts are now executable"

# ── Step 2: Shared / server-level settings ────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 2 — Server & Shared Settings"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ask "Server IP address [72.62.239.220]:"
read -r SERVER_IP
SERVER_IP="${SERVER_IP:-72.62.239.220}"

ask "Alert / SSL email address [admin@tadgeeg.com]:"
read -r ALERT_EMAIL
ALERT_EMAIL="${ALERT_EMAIL:-admin@tadgeeg.com}"

ask "Django settings module [finai_backend.settings]:"
read -r DJANGO_SETTINGS_MODULE
DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-finai_backend.settings}"

# ── Helper: write one env file ────────────────────────────────────────────────
write_env_file() {
  local ENV_NAME="$1"         # live | dev | test
  local ENV_LABEL="$2"        # LIVE | DEV | TEST
  local DOMAIN_MAIN="$3"
  local DOMAIN_WWW="$4"
  local BRANCH="$5"
  local WEB_ROOT="$6"
  local PORT="$7"
  local WORKERS="$8"
  local TIMEOUT="$9"
  local MAX_REQ="${10}"
  local REDIS_DB="${11}"
  local DEBUG="${12}"
  local DJANGO_ENV="${13}"

  local FILE="$CONFIG_DIR/${ENV_NAME}.env"

  cat > "$FILE" <<ENV
# ============================================================
# FinAI — ${ENV_LABEL} Environment Configuration
# Generated: $(date '+%F %T') by setup_server.sh
# ============================================================
ENV_NAME="${ENV_NAME}"
ENV_LABEL="${ENV_LABEL}"

# --- Server ---
SERVER_IP="${SERVER_IP}"
WEB_ROOT="${WEB_ROOT}"
SOCKET="/run/finai_${ENV_NAME}.sock"
SERVICE_NAME="finai_${ENV_NAME}"
PORT_GUNICORN_INTERNAL="${PORT}"

# --- Domains ---
DOMAIN_MAIN="${DOMAIN_MAIN}"
DOMAIN_WWW="${DOMAIN_WWW}"
DOMAIN_ALL="${DOMAIN_MAIN} ${DOMAIN_WWW}"

# --- Git ---
REPO_URL="${REPO_URL}"
SYNC_REPO_URL="${CLONE_URL}"
BRANCH="${BRANCH}"
PROJECT_ROOT="${WEB_ROOT}"
BACKEND_DIR="${WEB_ROOT}"
VENV_DIR="${WEB_ROOT}/venv"

# --- Nginx ---
NGINX_SITE_NAME="finai_${ENV_NAME}"
NGINX_SITE_FILE="/etc/nginx/sites-available/finai_${ENV_NAME}"
NGINX_ENABLED_FILE="/etc/nginx/sites-enabled/finai_${ENV_NAME}"
STATIC_ROOT="${WEB_ROOT}/static"
MEDIA_ROOT="${WEB_ROOT}/media"
LOG_DIR="/var/log/finai/${ENV_NAME}"

# --- Database (MySQL) ---
DB_NAME="finai_${ENV_NAME}"
DB_USER="finai_${ENV_NAME}_user"
DB_HOST="127.0.0.1"
DB_PORT="3306"
# DB_PASSWORD — set in .secret.env, never committed to git

# --- Django ---
DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE}"
DJANGO_ENV="${DJANGO_ENV}"
ALLOWED_HOSTS="${DOMAIN_MAIN},${DOMAIN_WWW},${SERVER_IP}"
DEBUG="${DEBUG}"

# --- SSL ---
SSL_EMAIL="${ALERT_EMAIL}"
USE_SSL="true"

# --- Gunicorn ---
GUNICORN_WORKERS="${WORKERS}"
GUNICORN_TIMEOUT="${TIMEOUT}"
GUNICORN_MAX_REQUESTS="${MAX_REQ}"

# --- Redis ---
REDIS_URL="redis://127.0.0.1:6379/${REDIS_DB}"

# --- Docker ---
DOCKER_COMPOSE_FILE="docker-compose.${ENV_NAME}.yml"
DOCKER_PROJECT_NAME="finai_${ENV_NAME}"
ENV

  success "${ENV_LABEL} config written → $FILE"
}

# ── Step 3: LIVE environment ───────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 3 — LIVE Environment  (tadgeeg.com)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ask "Main domain for LIVE [tadgeeg.com]:"
read -r LIVE_DOMAIN
LIVE_DOMAIN="${LIVE_DOMAIN:-tadgeeg.com}"

ask "WWW domain for LIVE [www.tadgeeg.com]:"
read -r LIVE_WWW
LIVE_WWW="${LIVE_WWW:-www.${LIVE_DOMAIN}}"

ask "Git branch for LIVE [main]:"
read -r LIVE_BRANCH
LIVE_BRANCH="${LIVE_BRANCH:-main}"

ask "Web root for LIVE [/var/www/live]:"
read -r LIVE_ROOT
LIVE_ROOT="${LIVE_ROOT:-/var/www/live}"

write_env_file \
  "live" "LIVE" \
  "$LIVE_DOMAIN" "$LIVE_WWW" \
  "$LIVE_BRANCH" "$LIVE_ROOT" \
  "8001" "5" "120" "1000" "0" \
  "False" "production"

# ── Step 4: DEV environment ───────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 4 — DEV Environment  (dev.tadgeeg.com)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ask "Main domain for DEV [dev.tadgeeg.com]:"
read -r DEV_DOMAIN
DEV_DOMAIN="${DEV_DOMAIN:-dev.tadgeeg.com}"

ask "WWW domain for DEV [www.dev.tadgeeg.com]:"
read -r DEV_WWW
DEV_WWW="${DEV_WWW:-www.${DEV_DOMAIN}}"

ask "Git branch for DEV [dev]:"
read -r DEV_BRANCH
DEV_BRANCH="${DEV_BRANCH:-dev}"

ask "Web root for DEV [/var/www/dev]:"
read -r DEV_ROOT
DEV_ROOT="${DEV_ROOT:-/var/www/dev}"

write_env_file \
  "dev" "DEV" \
  "$DEV_DOMAIN" "$DEV_WWW" \
  "$DEV_BRANCH" "$DEV_ROOT" \
  "8002" "3" "180" "500" "1" \
  "True" "development"

# ── Step 5: TEST environment ──────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 5 — TEST Environment  (test.tadgeeg.com)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ask "Main domain for TEST [test.tadgeeg.com]:"
read -r TEST_DOMAIN
TEST_DOMAIN="${TEST_DOMAIN:-test.tadgeeg.com}"

ask "WWW domain for TEST [www.test.tadgeeg.com]:"
read -r TEST_WWW
TEST_WWW="${TEST_WWW:-www.${TEST_DOMAIN}}"

ask "Git branch for TEST [test]:"
read -r TEST_BRANCH
TEST_BRANCH="${TEST_BRANCH:-test}"

ask "Web root for TEST [/var/www/test]:"
read -r TEST_ROOT
TEST_ROOT="${TEST_ROOT:-/var/www/test}"

write_env_file \
  "test" "TEST" \
  "$TEST_DOMAIN" "$TEST_WWW" \
  "$TEST_BRANCH" "$TEST_ROOT" \
  "8003" "2" "180" "200" "2" \
  "True" "testing"

# ── Step 6: Secret files (.secret.env) ───────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  STEP 6 — Secret Keys & Credentials"
echo "  (written to /var/www/<env>/.secret.env — never in Git)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ask "Create .secret.env files now? [y/N]:"
read -r CREATE_SECRETS

if [[ "${CREATE_SECRETS,,}" == "y" || "${CREATE_SECRETS,,}" == "yes" ]]; then

  # ── OpenAI ────────────────────────────────────────────────────────────────
  ask "OpenAI API Key (sk-...):"
  read -rs OPENAI_API_KEY; echo ""

  ask "OpenAI model [gpt-4o]:"
  read -r OPENAI_MODEL
  OPENAI_MODEL="${OPENAI_MODEL:-gpt-4o}"

  ask "OpenAI max tokens [4096]:"
  read -r OPENAI_MAX_TOKENS
  OPENAI_MAX_TOKENS="${OPENAI_MAX_TOKENS:-4096}"

  echo ""
  echo "  Google OAuth settings"
  echo "  Leave Client ID blank to skip Google OAuth on deployed environments."
  echo ""
  ask "Google Client ID (leave blank to skip):"
  read -r GOOGLE_CLIENT_ID

  if [ -n "$GOOGLE_CLIENT_ID" ]; then
    ask "Google Client Secret:"
    read -rs GOOGLE_CLIENT_SECRET; echo ""
    [ -n "$GOOGLE_CLIENT_SECRET" ] || fail "Google Client Secret cannot be empty when Client ID is provided"
  else
    GOOGLE_CLIENT_SECRET=""
  fi

  # ── Email / SMTP ──────────────────────────────────────────────────────────
  echo ""
  echo "  Email / SMTP settings (alerts, password reset, reports)"
  echo "  Leave username blank to skip — console backend will be used."
  echo ""
  ask "SMTP host [smtp.gmail.com]:"
  read -r EMAIL_HOST
  EMAIL_HOST="${EMAIL_HOST:-smtp.gmail.com}"

  ask "SMTP port [587]:"
  read -r EMAIL_PORT
  EMAIL_PORT="${EMAIL_PORT:-587}"

  ask "SMTP username / email (e.g. alerts@tadgeeg.com):"
  read -r EMAIL_HOST_USER

  ask "SMTP password / app password:"
  read -rs EMAIL_HOST_PASSWORD; echo ""

  ask "Default FROM email [$EMAIL_HOST_USER]:"
  read -r DEFAULT_FROM_EMAIL
  DEFAULT_FROM_EMAIL="${DEFAULT_FROM_EMAIL:-${EMAIL_HOST_USER:-noreply@tadgeeg.com}}"

  # Per-environment secrets
  for ENV_NAME in live dev test; do
    case "$ENV_NAME" in
      live) WEB_ROOT="$LIVE_ROOT" ;;
      dev)  WEB_ROOT="$DEV_ROOT"  ;;
      test) WEB_ROOT="$TEST_ROOT" ;;
    esac

    ask "Django SECRET_KEY for ${ENV_NAME^^} (leave blank to auto-generate):"
    read -rs SECRET_KEY
    echo ""
    if [ -z "$SECRET_KEY" ]; then
      SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))" 2>/dev/null \
        || cat /dev/urandom | tr -dc 'A-Za-z0-9!@#$%^&*' | head -c 50)
    fi

    ask "DB_PASSWORD for ${ENV_NAME^^}:"
    read -rs DB_PASSWORD
    echo ""

    ask "DB_ROOT_PASSWORD for ${ENV_NAME^^}:"
    read -rs DB_ROOT_PASSWORD
    echo ""

    mkdir -p "$WEB_ROOT"
    SECRET_FILE="$WEB_ROOT/.secret.env"

    # Determine domain and allowed hosts per env
    case "$ENV_NAME" in
      live) _DOMAIN="$LIVE_DOMAIN"  ;;
      dev)  _DOMAIN="$DEV_DOMAIN"   ;;
      test) _DOMAIN="$TEST_DOMAIN"  ;;
    esac

    GOOGLE_BLOCK=""
    if [ -n "${GOOGLE_CLIENT_ID:-}" ] && [ -n "${GOOGLE_CLIENT_SECRET:-}" ]; then
      GOOGLE_BLOCK=$(cat <<GOOGLE

# ── Google OAuth ──────────────────────────────────────────
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
GOOGLE_REDIRECT_URI=https://${_DOMAIN}/auth/google/callback/
GOOGLE
)
    fi

    cat > "$SECRET_FILE" <<SECRET
# ── Django ────────────────────────────────────────────────
SECRET_KEY=${SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=${_DOMAIN},www.${_DOMAIN},${SERVER_IP}

# ── Database (MySQL) ──────────────────────────────────────
DB_ENGINE=django.db.backends.mysql
DB_NAME=finai_${ENV_NAME}
DB_USER=finai_${ENV_NAME}_user
DB_PASSWORD=${DB_PASSWORD}
DB_HOST=127.0.0.1
DB_PORT=3306

# ── OpenAI ────────────────────────────────────────────────
OPENAI_API_KEY=${OPENAI_API_KEY}
OPENAI_MODEL=${OPENAI_MODEL}
OPENAI_MAX_TOKENS=${OPENAI_MAX_TOKENS}
OPENAI_TIMEOUT=30
${GOOGLE_BLOCK}

# ── Email / SMTP ──────────────────────────────────────────
EMAIL_HOST=${EMAIL_HOST}
EMAIL_PORT=${EMAIL_PORT}
EMAIL_HOST_USER=${EMAIL_HOST_USER}
EMAIL_HOST_PASSWORD=${EMAIL_HOST_PASSWORD}
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=${DEFAULT_FROM_EMAIL}
SITE_URL=https://${_DOMAIN}
WASSLA_EMAIL_ASYNC_ENABLED=True

# ── Alerts ────────────────────────────────────────────────
ALERT_EMAIL=${ALERT_EMAIL}
DB_ROOT_PASSWORD=${DB_ROOT_PASSWORD}
SECRET

    chmod 600 "$SECRET_FILE"
    success "${ENV_NAME^^} secrets → $SECRET_FILE (permissions: 600)"
  done
else
  echo ""
  warn "Skipped. Create them manually before running deploy:"
  for ENV_NAME in live dev test; do
    case "$ENV_NAME" in
      live) WEB_ROOT="$LIVE_ROOT" ;;
      dev)  WEB_ROOT="$DEV_ROOT"  ;;
      test) WEB_ROOT="$TEST_ROOT" ;;
    esac
    echo "  $WEB_ROOT/.secret.env"
  done
  echo ""
  echo "  Required keys in each .secret.env:"
  echo "    SECRET_KEY=<django-secret>"
  echo "    DEBUG=False"
  echo "    DB_ENGINE=django.db.backends.mysql"
  echo "    DB_NAME=finai_<env>"
  echo "    DB_USER=finai_<env>_user"
  echo "    DB_PASSWORD=<password>"
  echo "    DB_HOST=127.0.0.1"
  echo "    DB_PORT=3306"
  echo "    OPENAI_API_KEY=sk-..."
  echo "    GOOGLE_CLIENT_ID=<optional-google-client-id>"
  echo "    GOOGLE_CLIENT_SECRET=<optional-google-client-secret>"
  echo "    GOOGLE_REDIRECT_URI=https://<domain>/auth/google/callback/"
  echo "    ALERT_EMAIL=${ALERT_EMAIL}"
  echo "    DB_ROOT_PASSWORD=<root-password>"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ✅  Setup Complete                                      ║"
echo "╠══════════════════════════════════════════════════════════╣"
printf "║  Project cloned to : %-37s ║\n" "$DEPLOY_DIR"
printf "║  Config files at   : %-37s ║\n" "$CONFIG_DIR"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Generated config files:"
echo "    ✅  $CONFIG_DIR/live.env"
echo "    ✅  $CONFIG_DIR/dev.env"
echo "    ✅  $CONFIG_DIR/test.env"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Update REPO_URL in each config if different:"
echo "       nano $CONFIG_DIR/live.env"
echo ""
echo "  2. Run full deployment (one per environment):"
echo "       cd $DEPLOY_DIR/deployment"
echo "       bash deploy_finish.sh live"
echo "       bash deploy_finish.sh dev"
echo "       bash deploy_finish.sh test"
echo ""
echo "  3. Or run quick refresh after code changes:"
echo "       bash refresh.sh live"
echo ""
echo "  4. Optional — install git auto-deploy daemon:"
echo "       bash git_.sh install"
echo ""
