#!/bin/bash
# ============================================================
# FinAI — Full Server Initialization Script
# Usage: bash server_init.sh
#
# Run this ONCE on a fresh Ubuntu 22.04 server.
# Collects all required inputs upfront, then runs everything
# automatically:
#   1.  System update & packages
#   2.  MySQL install + secure + create DBs & users
#   3.  Clone project & write env configs
#   4.  Write .secret.env files
#   5.  Full deployment: dev → test → live
#   6.  Django superuser creation
#   7.  Git auto-deploy daemon (optional)
# ============================================================
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info()    { echo -e "${CYAN}[INFO]${RESET}  $1"; }
success() { echo -e "${GREEN}[ OK ]${RESET}  $1"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $1"; }
fail()    { echo -e "${RED}[FAIL]${RESET}  $1"; exit 1; }
section() { echo ""; echo -e "${BOLD}━━━  $1  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"; echo ""; }
ask()     { echo -en "${BOLD}▶ $1${RESET} "; }

MYSQL_AUTH_MODE=""
MYSQL_AUTH_ARGS=()
DEBIAN_MYSQL_DEFAULTS="/etc/mysql/debian.cnf"
MYSQL_ROOT_CURRENT_PASS=""
APT_RETRY_COUNT="${APT_RETRY_COUNT:-3}"

run_with_retries() {
  local description="$1"
  shift
  local attempt=1

  until "$@"; do
    if [ "$attempt" -ge "$APT_RETRY_COUNT" ]; then
      fail "${description} failed after ${APT_RETRY_COUNT} attempts"
    fi

    warn "${description} failed (attempt ${attempt}/${APT_RETRY_COUNT}) — retrying in 5 seconds..."
    attempt=$((attempt + 1))
    sleep 5
  done
}

apt_update() {
  run_with_retries "apt-get update" apt-get update -y
}

apt_upgrade() {
  run_with_retries "apt-get upgrade" apt-get upgrade -y
}

apt_install() {
  [ "$#" -gt 0 ] || return 0
  run_with_retries "apt-get install: $*" apt-get install -y "$@"
}

try_mysql_password_auth() {
  local password="$1"
  local mode="$2"

  [ -n "$password" ] || return 1

  if mysql -u root -p"$password" -e "SELECT 1" >/dev/null 2>&1; then
    MYSQL_AUTH_MODE="$mode"
    MYSQL_AUTH_ARGS=(-u root -p"$password")
    return 0
  fi

  return 1
}

detect_mysql_auth() {
  MYSQL_AUTH_MODE=""
  MYSQL_AUTH_ARGS=()

  if try_mysql_password_auth "${MYSQL_ROOT_CURRENT_PASS:-}" "root-current-password"; then
    return 0
  fi

  if try_mysql_password_auth "${MYSQL_ROOT_PASS:-}" "root-target-password"; then
    return 0
  fi

  if mysql -u root -e "SELECT 1" >/dev/null 2>&1; then
    MYSQL_AUTH_MODE="root-socket"
    MYSQL_AUTH_ARGS=(-u root)
    return 0
  fi

  if [ -f "$DEBIAN_MYSQL_DEFAULTS" ] && mysql --defaults-file="$DEBIAN_MYSQL_DEFAULTS" -e "SELECT 1" >/dev/null 2>&1; then
    MYSQL_AUTH_MODE="debian-maint"
    MYSQL_AUTH_ARGS=(--defaults-file="$DEBIAN_MYSQL_DEFAULTS")
    return 0
  fi

  return 1
}

mysql_exec() {
  mysql "${MYSQL_AUTH_ARGS[@]}" "$@"
}

prompt_for_mysql_auth_retry() {
  [ -t 0 ] || return 1

  local attempt=1
  while [ "$attempt" -le 3 ]; do
    echo ""
    warn "Unable to authenticate to MySQL with the current values."
    ask "Enter CURRENT MySQL root password (attempt ${attempt}/3, leave blank if socket auth should work):"
    read -rs MYSQL_ROOT_CURRENT_PASS; echo ""

    if detect_mysql_auth; then
      return 0
    fi

    attempt=$((attempt + 1))
  done

  return 1
}

mysql_exec_or_fail() {
  if ! detect_mysql_auth; then
    prompt_for_mysql_auth_retry || fail "Unable to authenticate to MySQL. Provide the existing MySQL root password, or verify $DEBIAN_MYSQL_DEFAULTS exists and is valid."
    detect_mysql_auth || fail "Unable to authenticate to MySQL. Provide the existing MySQL root password, or verify $DEBIAN_MYSQL_DEFAULTS exists and is valid."
  fi

  case "$MYSQL_AUTH_MODE" in
    root-current-password)
      info "Authenticated to MySQL with the existing root password"
      ;;
    root-target-password)
      info "Authenticated to MySQL with the target root password"
      ;;
    root-socket)
      warn "Authenticated to MySQL via local socket; applying the supplied root password now"
      ;;
    debian-maint)
      warn "Using Debian maintenance credentials to apply the supplied root password"
      ;;
  esac

  mysql_exec "$@"
}

# ── Root check ────────────────────────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || fail "Must run as root: sudo bash server_init.sh"

# ── Header ────────────────────────────────────────────────────────────────────
clear
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   FinAI — Full Server Initialization                     ║"
echo "║   Ubuntu 22.04 · Django · Gunicorn · Nginx · MySQL       ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  This script will configure the entire server from scratch."
echo "  You will be asked for credentials ONCE, then everything"
echo "  runs automatically (~25–40 minutes total)."
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 0 — Collect all inputs upfront
# ═══════════════════════════════════════════════════════════════════════════════
section "INPUTS — Enter everything now, then sit back"

# ── GitHub ────────────────────────────────────────────────────────────────────
ask "GitHub repo URL [https://github.com/mohammed0115/tadgeeg.git]:"
read -r REPO_URL
REPO_URL="${REPO_URL:-https://github.com/mohammed0115/tadgeeg.git}"

ask "GitHub Personal Access Token (ghp_... — for private repo, else leave blank):"
read -rs GITHUB_TOKEN; echo ""
if [ -n "$GITHUB_TOKEN" ]; then
  CLONE_URL="${REPO_URL/https:\/\//https://${GITHUB_TOKEN}@}"
else
  CLONE_URL="$REPO_URL"
fi

# ── Server ────────────────────────────────────────────────────────────────────
ask "Server IP [72.62.239.220]:"
read -r SERVER_IP
SERVER_IP="${SERVER_IP:-72.62.239.220}"

ask "Alert email [admin@tadgeeg.com]:"
read -r ALERT_EMAIL
ALERT_EMAIL="${ALERT_EMAIL:-admin@tadgeeg.com}"

# ── OpenAI ────────────────────────────────────────────────────────────────────
ask "OpenAI API Key (sk-...):"
read -rs OPENAI_KEY; echo ""
[ -n "$OPENAI_KEY" ] || fail "OpenAI API key is required"

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

# ── MySQL root password ───────────────────────────────────────────────────────
ask "MySQL ROOT password (existing if already configured; new on fresh installs):"
read -rs MYSQL_ROOT_PASS; echo ""
[ -n "$MYSQL_ROOT_PASS" ] || fail "MySQL root password cannot be empty"

ask "Current MySQL ROOT password if already configured (leave blank for fresh installs/socket auth):"
read -rs MYSQL_ROOT_CURRENT_PASS; echo ""

# ── Per-environment DB passwords ──────────────────────────────────────────────
ask "DB password for LIVE environment:"
read -rs DB_PASS_LIVE; echo ""
[ -n "$DB_PASS_LIVE" ] || fail "DB_PASS_LIVE cannot be empty"

ask "DB password for DEV environment:"
read -rs DB_PASS_DEV; echo ""
[ -n "$DB_PASS_DEV" ] || fail "DB_PASS_DEV cannot be empty"

ask "DB password for TEST environment:"
read -rs DB_PASS_TEST; echo ""
[ -n "$DB_PASS_TEST" ] || fail "DB_PASS_TEST cannot be empty"

# ── Django secret keys (auto-generate if blank) ───────────────────────────────
gen_secret() {
  python3 -c "import secrets; print(secrets.token_urlsafe(50))" 2>/dev/null \
    || cat /dev/urandom | tr -dc 'A-Za-z0-9!@#$%^&*' | head -c 50
}

ask "Django SECRET_KEY for LIVE (leave blank to auto-generate):"
read -rs DJANGO_SECRET_LIVE; echo ""
DJANGO_SECRET_LIVE="${DJANGO_SECRET_LIVE:-$(gen_secret)}"

ask "Django SECRET_KEY for DEV (leave blank to auto-generate):"
read -rs DJANGO_SECRET_DEV; echo ""
DJANGO_SECRET_DEV="${DJANGO_SECRET_DEV:-$(gen_secret)}"

ask "Django SECRET_KEY for TEST (leave blank to auto-generate):"
read -rs DJANGO_SECRET_TEST; echo ""
DJANGO_SECRET_TEST="${DJANGO_SECRET_TEST:-$(gen_secret)}"

# ── Email (SMTP) ──────────────────────────────────────────────────────────────
echo ""
echo "  Email / SMTP settings (used for alerts, password reset, reports)"
echo "  Leave blank to skip — email features will use console backend."
echo ""
ask "SMTP host [smtp.gmail.com]:"
read -r EMAIL_HOST
EMAIL_HOST="${EMAIL_HOST:-smtp.gmail.com}"

ask "SMTP port [587]:"
read -r EMAIL_PORT
EMAIL_PORT="${EMAIL_PORT:-587}"

ask "SMTP username / email address (e.g. alerts@tadgeeg.com):"
read -r EMAIL_HOST_USER

ask "SMTP password / app password (leave blank to skip):"
read -rs EMAIL_HOST_PASSWORD; echo ""

ask "Default FROM email [$EMAIL_HOST_USER]:"
read -r DEFAULT_FROM_EMAIL
DEFAULT_FROM_EMAIL="${DEFAULT_FROM_EMAIL:-${EMAIL_HOST_USER:-noreply@tadgeeg.com}}"

# ── OpenAI model ──────────────────────────────────────────────────────────────
echo ""
ask "OpenAI model [gpt-4o]:"
read -r OPENAI_MODEL
OPENAI_MODEL="${OPENAI_MODEL:-gpt-4o}"

ask "OpenAI max tokens [4096]:"
read -r OPENAI_MAX_TOKENS
OPENAI_MAX_TOKENS="${OPENAI_MAX_TOKENS:-4096}"

# ── Superuser ─────────────────────────────────────────────────────────────────
ask "Django superuser username [admin]:"
read -r SU_USERNAME
SU_USERNAME="${SU_USERNAME:-admin}"

ask "Django superuser email [$ALERT_EMAIL]:"
read -r SU_EMAIL
SU_EMAIL="${SU_EMAIL:-$ALERT_EMAIL}"

ask "Django superuser password:"
read -rs SU_PASSWORD; echo ""
[ -n "$SU_PASSWORD" ] || fail "Superuser password cannot be empty"

# ── Auto-deploy ───────────────────────────────────────────────────────────────
ask "Install git auto-deploy daemon? [y/N]:"
read -r INSTALL_AUTODEPLOY

# ── Deploy which environments? ────────────────────────────────────────────────
ask "Deploy environments (comma-separated: dev,test,live) [dev,test,live]:"
read -r DEPLOY_ENVS
DEPLOY_ENVS="${DEPLOY_ENVS:-dev,test,live}"

# ── Confirm ───────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Review before proceeding                                ║"
echo "╠══════════════════════════════════════════════════════════╣"
printf "║  Repo      : %-43s ║\n" "$REPO_URL"
printf "║  Server IP : %-43s ║\n" "$SERVER_IP"
printf "║  Email     : %-43s ║\n" "$ALERT_EMAIL"
printf "║  Superuser : %-43s ║\n" "$SU_USERNAME"
printf "║  Envs      : %-43s ║\n" "$DEPLOY_ENVS"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
ask "Everything correct? Type 'yes' to start:"
read -r CONFIRM
[ "$CONFIRM" = "yes" ] || { echo "Aborted."; exit 0; }

# ── Logging ───────────────────────────────────────────────────────────────────
INIT_LOG="/var/log/finai_server_init.log"
mkdir -p "$(dirname "$INIT_LOG")"
exec > >(tee -a "$INIT_LOG") 2>&1
echo "$(date '+%F %T') — Server init started"

DEPLOY_DIR="/root/finai-deploy"
SCRIPT_DIR="$DEPLOY_DIR/deployment"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — System update & base packages
# ═══════════════════════════════════════════════════════════════════════════════
section "STEP 1 — System Update"

apt_update
apt_upgrade
apt_install \
  git curl wget gnupg lsb-release \
  build-essential software-properties-common \
  ufw fail2ban ca-certificates

success "System updated and base packages installed"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Install MySQL
# ═══════════════════════════════════════════════════════════════════════════════
section "STEP 2 — MySQL Installation"

if command -v mysql &>/dev/null && systemctl list-unit-files | grep -q '^mysql.service'; then
  success "MySQL already installed ($(mysql --version | awk '{print $3}'))"
else
  info "Installing MySQL Server..."
  apt_install mysql-server
  success "MySQL installed"
fi

systemctl enable mysql
systemctl start mysql
systemctl is-active --quiet mysql || fail "MySQL service failed to start"

mysql_escape_string() {
  printf "%s" "$1" | sed -e 's/\\/\\\\/g' -e "s/'/''/g"
}

MYSQL_ROOT_PASS_SQL="$(mysql_escape_string "$MYSQL_ROOT_PASS")"
DB_PASS_LIVE_SQL="$(mysql_escape_string "$DB_PASS_LIVE")"
DB_PASS_DEV_SQL="$(mysql_escape_string "$DB_PASS_DEV")"
DB_PASS_TEST_SQL="$(mysql_escape_string "$DB_PASS_TEST")"

# Secure MySQL without interactive prompt
info "Securing MySQL..."
mysql_exec_or_fail <<SQL
  ALTER USER 'root'@'localhost' IDENTIFIED BY '${MYSQL_ROOT_PASS_SQL}';
  DELETE FROM mysql.user WHERE User='';
  DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost','127.0.0.1','::1');
  DROP DATABASE IF EXISTS test;
  DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';
  FLUSH PRIVILEGES;
SQL
MYSQL_AUTH_MODE="root-password"
MYSQL_AUTH_ARGS=(-u root -p"${MYSQL_ROOT_PASS}")
success "MySQL secured"

# Create databases and users
info "Creating databases and users..."
mysql_exec <<SQL
  -- Live
  CREATE DATABASE IF NOT EXISTS \`finai_live\`
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  CREATE USER IF NOT EXISTS 'finai_live_user'@'127.0.0.1'
    IDENTIFIED BY '${DB_PASS_LIVE_SQL}';
  GRANT ALL PRIVILEGES ON \`finai_live\`.* TO 'finai_live_user'@'127.0.0.1';

  -- Dev
  CREATE DATABASE IF NOT EXISTS \`finai_dev\`
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  CREATE USER IF NOT EXISTS 'finai_dev_user'@'127.0.0.1'
    IDENTIFIED BY '${DB_PASS_DEV_SQL}';
  GRANT ALL PRIVILEGES ON \`finai_dev\`.* TO 'finai_dev_user'@'127.0.0.1';

  -- Test
  CREATE DATABASE IF NOT EXISTS \`finai_test\`
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  CREATE USER IF NOT EXISTS 'finai_test_user'@'127.0.0.1'
    IDENTIFIED BY '${DB_PASS_TEST_SQL}';
  GRANT ALL PRIVILEGES ON \`finai_test\`.* TO 'finai_test_user'@'127.0.0.1';

  FLUSH PRIVILEGES;
SQL
success "Databases and users created: finai_live, finai_dev, finai_test"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Clone repository
# ═══════════════════════════════════════════════════════════════════════════════
section "STEP 3 — Clone Repository"

if [ -d "$DEPLOY_DIR/.git" ]; then
  info "Repo already exists — pulling latest..."
  git -C "$DEPLOY_DIR" remote set-url origin "$CLONE_URL" 2>/dev/null || true
  git -C "$DEPLOY_DIR" fetch origin --quiet
  git -C "$DEPLOY_DIR" reset --hard origin/main 2>/dev/null \
    || git -C "$DEPLOY_DIR" reset --hard origin/master 2>/dev/null || true
  success "Repository updated at $DEPLOY_DIR"
else
  info "Cloning $REPO_URL → $DEPLOY_DIR ..."
  git clone "$CLONE_URL" "$DEPLOY_DIR" || fail "Git clone failed — check URL and token"
  success "Repository cloned"
fi

chmod +x "$SCRIPT_DIR"/*.sh
success "All deployment scripts are executable"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Write env config files
# ═══════════════════════════════════════════════════════════════════════════════
section "STEP 4 — Write Environment Config Files"

CONFIG_DIR="$SCRIPT_DIR/config"
mkdir -p "$CONFIG_DIR"

write_env() {
  local ENV_NAME="$1" ENV_LABEL="$2" DOMAIN_MAIN="$3" DOMAIN_WWW="$4"
  local BRANCH="$5" WEB_ROOT="$6" PORT="$7" WORKERS="$8"
  local TIMEOUT="$9" MAX_REQ="${10}" REDIS_DB="${11}"
  local DEBUG="${12}" DJANGO_ENV="${13}"

  cat > "$CONFIG_DIR/${ENV_NAME}.env" <<ENV
# ============================================================
# FinAI — ${ENV_LABEL} Environment Configuration
# Generated: $(date '+%F %T') by server_init.sh
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

# --- Django ---
DJANGO_SETTINGS_MODULE="finai_backend.settings"
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
  success "${ENV_LABEL} → $CONFIG_DIR/${ENV_NAME}.env"
}

write_env "live" "LIVE" \
  "tadgeeg.com" "www.tadgeeg.com" \
  "main" "/var/www/live" \
  "8001" "5" "120" "1000" "0" \
  "False" "production"

write_env "dev" "DEV" \
  "dev.tadgeeg.com" "www.dev.tadgeeg.com" \
  "dev" "/var/www/dev" \
  "8002" "3" "180" "500" "1" \
  "True" "development"

write_env "test" "TEST" \
  "test.tadgeeg.com" "www.test.tadgeeg.com" \
  "test" "/var/www/test" \
  "8003" "2" "180" "200" "2" \
  "True" "testing"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Write .secret.env files
# ═══════════════════════════════════════════════════════════════════════════════
section "STEP 5 — Write Secret Files"

write_secret() {
  local WEB_ROOT="$1" SECRET_KEY="$2" DB_PASS="$3" DB_NAME="$4" DB_USER="$5"
  local ALLOWED_HOSTS_VAR="$6" DOMAIN_VAR="$7"
  local GOOGLE_BLOCK=""

  if [ -n "${GOOGLE_CLIENT_ID:-}" ] && [ -n "${GOOGLE_CLIENT_SECRET:-}" ]; then
    GOOGLE_BLOCK=$(cat <<GOOGLE

# ── Google OAuth ──────────────────────────────────────────
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
GOOGLE_REDIRECT_URI=https://${DOMAIN_VAR}/auth/google/callback/
GOOGLE
)
  fi

  mkdir -p "$WEB_ROOT"
  cat > "$WEB_ROOT/.secret.env" <<SECRET
# ── Django ────────────────────────────────────────────────
SECRET_KEY=${SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=${ALLOWED_HOSTS_VAR}

# ── Database (MySQL) ──────────────────────────────────────
DB_ENGINE=django.db.backends.mysql
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASS}
DB_HOST=127.0.0.1
DB_PORT=3306

# ── OpenAI ────────────────────────────────────────────────
OPENAI_API_KEY=${OPENAI_KEY}
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
SITE_URL=https://${DOMAIN_VAR}
WASSLA_EMAIL_ASYNC_ENABLED=True

# ── Alerts ────────────────────────────────────────────────
ALERT_EMAIL=${ALERT_EMAIL}
DB_ROOT_PASSWORD=${MYSQL_ROOT_PASS}
SECRET
  chmod 600 "$WEB_ROOT/.secret.env"
  success "Written: $WEB_ROOT/.secret.env (chmod 600)"
}

write_secret "/var/www/live" "$DJANGO_SECRET_LIVE" "$DB_PASS_LIVE" "finai_live" "finai_live_user" \
  "tadgeeg.com,www.tadgeeg.com,${SERVER_IP}" "tadgeeg.com"
write_secret "/var/www/dev"  "$DJANGO_SECRET_DEV"  "$DB_PASS_DEV"  "finai_dev"  "finai_dev_user" \
  "dev.tadgeeg.com,www.dev.tadgeeg.com,${SERVER_IP}" "dev.tadgeeg.com"
write_secret "/var/www/test" "$DJANGO_SECRET_TEST" "$DB_PASS_TEST" "finai_test" "finai_test_user" \
  "test.tadgeeg.com,www.test.tadgeeg.com,${SERVER_IP}" "test.tadgeeg.com"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Full deployment per environment
# ═══════════════════════════════════════════════════════════════════════════════
section "STEP 6 — Deploy Environments"

cd "$SCRIPT_DIR"

deploy_env() {
  local ENV="$1"
  echo ""
  echo "──────────────────────────────────────────────────────────"
  info "Deploying [$ENV] environment..."
  echo "──────────────────────────────────────────────────────────"

  # Pipe 'yes' to bypass live confirmation prompt
  if [ "$ENV" = "live" ]; then
    echo "yes" | bash "$SCRIPT_DIR/deploy_finish.sh" "$ENV" \
      && success "[$ENV] deployment COMPLETE" \
      || fail "[$ENV] deployment FAILED — check $INIT_LOG"
  else
    bash "$SCRIPT_DIR/deploy_finish.sh" "$ENV" \
      && success "[$ENV] deployment COMPLETE" \
      || fail "[$ENV] deployment FAILED — check $INIT_LOG"
  fi
}

IFS=',' read -ra ENV_LIST <<< "$DEPLOY_ENVS"
for ENV in "${ENV_LIST[@]}"; do
  ENV="$(echo "$ENV" | tr -d ' ')"
  case "$ENV" in
    dev|test|live) deploy_env "$ENV" ;;
    *) warn "Unknown environment '$ENV' — skipping" ;;
  esac
done

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Create Django superuser (live env)
# ═══════════════════════════════════════════════════════════════════════════════
section "STEP 7 — Create Django Superuser"

LIVE_VENV="/var/www/live/venv"
LIVE_DIR="/var/www/live"

if [ -f "$LIVE_VENV/bin/activate" ] && [ -f "$LIVE_DIR/manage.py" ]; then
  info "Creating superuser: $SU_USERNAME"

  source "$LIVE_VENV/bin/activate"
  export DJANGO_SETTINGS_MODULE="finai_backend.settings"
  export SECRET_KEY="$DJANGO_SECRET_LIVE"
  export DB_NAME="finai_live"
  export DB_USER="finai_live_user"
  export DB_PASSWORD="$DB_PASS_LIVE"
  export DB_HOST="127.0.0.1"
  export REDIS_URL="redis://127.0.0.1:6379/0"
  export ALLOWED_HOSTS="tadgeeg.com,www.tadgeeg.com,$SERVER_IP"

  cd "$LIVE_DIR"
  python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='${SU_USERNAME}').exists():
    User.objects.create_superuser('${SU_USERNAME}', '${SU_EMAIL}', '${SU_PASSWORD}')
    print('Superuser created: ${SU_USERNAME}')
else:
    print('Superuser already exists: ${SU_USERNAME}')
" && success "Superuser ready: $SU_USERNAME"

  deactivate
else
  warn "Live venv not found — skipping superuser creation"
  warn "Run manually: cd /var/www/live && source venv/bin/activate && python manage.py createsuperuser"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 8 — Git auto-deploy daemon (optional)
# ═══════════════════════════════════════════════════════════════════════════════
if [[ "${INSTALL_AUTODEPLOY,,}" == "y" || "${INSTALL_AUTODEPLOY,,}" == "yes" ]]; then
  section "STEP 8 — Git Auto-Deploy Daemon"
  bash "$SCRIPT_DIR/git_.sh" install \
    && success "Auto-deploy daemon installed and running" \
    || warn "Auto-deploy install failed — run manually: bash deployment/git_.sh install"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 9 — Firewall
# ═══════════════════════════════════════════════════════════════════════════════
section "STEP 9 — Firewall (UFW)"

ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
success "Firewall configured: SSH + HTTP + HTTPS only"

# ═══════════════════════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ✅  Server Initialization Complete                      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Service Status:"
for SVC in finai_live finai_live_celery finai_live_celerybeat \
           finai_dev  finai_dev_celery \
           finai_test finai_test_celery \
           nginx redis-server; do
  STATUS=$(systemctl is-active "$SVC" 2>/dev/null || echo "not-found")
  [ "$STATUS" = "active" ] && ICON="✅" || ICON="⚠️ "
  printf "  %s  %-38s %s\n" "$ICON" "$SVC" "$STATUS"
done

echo ""
echo "  Smoke Tests:"
for ENV_NAME in $(echo "$DEPLOY_ENVS" | tr ',' ' '); do
  ENV_NAME="$(echo "$ENV_NAME" | tr -d ' ')"
  case "$ENV_NAME" in
    live) DOMAIN="tadgeeg.com" ;;
    dev)  DOMAIN="dev.tadgeeg.com" ;;
    test) DOMAIN="test.tadgeeg.com" ;;
    *)    continue ;;
  esac
  CODE=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 10 "https://${DOMAIN}/health/" 2>/dev/null || echo "000")
  [[ "$CODE" == "200" || "$CODE" == "301" || "$CODE" == "302" ]] \
    && ICON="✅" || ICON="⚠️ "
  printf "  %s  https://%-30s HTTP %s\n" "$ICON" "${DOMAIN}/health/" "$CODE"
done

echo ""
echo "  Useful commands:"
echo "    # View logs"
echo "    journalctl -u finai_live -f"
echo "    tail -f /var/log/finai/live/error.log"
echo ""
echo "    # Refresh after code changes"
echo "    bash $SCRIPT_DIR/refresh.sh live"
echo ""
echo "    # Admin panel"
echo "    https://tadgeeg.com/admin/"
echo "    Username: $SU_USERNAME"
echo ""
echo "    # Full init log"
echo "    cat $INIT_LOG"
echo ""
echo "$(date '+%F %T') — Server init finished" >> "$INIT_LOG"
