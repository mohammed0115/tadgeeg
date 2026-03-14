#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$SCRIPT_DIR/env"
DEPLOY_SCRIPT="$SCRIPT_DIR/deploy.sh"
LOG_DIR="$SCRIPT_DIR/logs"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="$LOG_DIR/bootstrap_${TIMESTAMP}.log"
LATEST_LOG="$LOG_DIR/bootstrap_latest.log"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1
ln -sfn "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true

on_error() {
  local exit_code=$?
  printf '%s [bootstrap] ERROR: command failed: %s (exit %s)\n' "$(date '+%F %T')" "$BASH_COMMAND" "$exit_code"
  printf '%s [bootstrap] ERROR: see log file %s\n' "$(date '+%F %T')" "$LOG_FILE"
  exit "$exit_code"
}

trap on_error ERR

log() {
  printf '%s [bootstrap] %s\n' "$(date '+%F %T')" "$1"
}

require_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "شغّل السكربت بصلاحية root: sudo bash deployment/docker/bootstrap_server.sh"
    exit 1
  fi
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker و Docker Compose موجودان بالفعل"
    return 0
  fi

  log "تثبيت Docker على Ubuntu 24.04"
  apt-get update
  apt-get install -y ca-certificates curl gnupg

  install -m 0755 -d /etc/apt/keyrings
  if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
  fi

  . /etc/os-release
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list

  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker

  log "Docker تم تثبيته بنجاح"
}

copy_env_if_missing() {
  local env_name="$1"
  local example_file="$ENV_DIR/${env_name}.env.example"
  local target_file="$ENV_DIR/${env_name}.env"

  if [ ! -f "$target_file" ]; then
    cp "$example_file" "$target_file"
    log "تم إنشاء $target_file"
  else
    log "الملف موجود بالفعل: $target_file"
  fi
}

random_secret() {
  python3 -c "import secrets; print(secrets.token_urlsafe(50))"
}

random_password() {
  python3 -c "import secrets; print(secrets.token_urlsafe(24))"
}

set_key_value() {
  local file="$1"
  local key="$2"
  local value="$3"

  python3 - "$file" "$key" "$value" <<'PY'
from pathlib import Path
import sys

file_path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]

lines = file_path.read_text(encoding='utf-8').splitlines()
updated = False
prefix = f"{key}="
for idx, line in enumerate(lines):
    if line.startswith(prefix):
        lines[idx] = f"{key}={value}"
        updated = True
        break

if not updated:
    lines.append(f"{key}={value}")

file_path.write_text("\n".join(lines) + "\n", encoding='utf-8')
PY
}

ensure_generated_values() {
  local env_name="$1"
  local file="$ENV_DIR/${env_name}.env"

  local django_secret
  django_secret="$(random_secret)"

  local db_password
  db_password="$(random_password)"

  local root_password
  root_password="$(random_password)"

  if grep -q '^DJANGO_SECRET_KEY=replace-' "$file"; then
    set_key_value "$file" "DJANGO_SECRET_KEY" "$django_secret"
  fi

  if grep -q '^SECRET_KEY=replace-' "$file"; then
    set_key_value "$file" "SECRET_KEY" "$django_secret"
  fi

  if grep -q '^DB_PASSWORD=change-' "$file"; then
    set_key_value "$file" "DB_PASSWORD" "$db_password"
  fi

  if grep -q '^MYSQL_PASSWORD=change-' "$file"; then
    set_key_value "$file" "MYSQL_PASSWORD" "$db_password"
  fi

  if grep -q '^MYSQL_ROOT_PASSWORD=change-' "$file"; then
    set_key_value "$file" "MYSQL_ROOT_PASSWORD" "$root_password"
  fi
}

bootstrap_env_files() {
  for env_name in live dev test; do
    copy_env_if_missing "$env_name"
    ensure_generated_values "$env_name"
  done
}

prepare_directories() {
  mkdir -p "$SCRIPT_DIR/nginx/generated" "$SCRIPT_DIR/certbot/www" "$SCRIPT_DIR/certbot/conf"
}

show_next_steps() {
  cat <<'EOF'

تم تشغيل stack Docker للبيئات الثلاث:
  - live
  - dev
  - test

ملف المتابعة:
  deployment/docker/logs/bootstrap_latest.log

أوامر مفيدة:
  bash deployment/docker/deploy.sh ps
  bash deployment/docker/deploy.sh logs nginx
  bash deployment/docker/deploy.sh logs web_live
  bash deployment/docker/deploy.sh logs web_dev
  bash deployment/docker/deploy.sh logs web_test

إنشاء مستخدم إدارة للبيئة live:
  docker compose -f deployment/docker/docker-compose.yml exec web_live python manage.py createsuperuser

راجع ملفات env إذا أردت إضافة:
  - GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
  - EMAIL_HOST_USER / EMAIL_HOST_PASSWORD
  - OPENAI_API_KEY
EOF
}

main() {
  require_root
  log "Bootstrap log file: $LOG_FILE"
  install_docker
  bootstrap_env_files
  prepare_directories
  bash "$SCRIPT_DIR/render_nginx_config.sh" http
  bash "$DEPLOY_SCRIPT" up all
  show_next_steps
}

main "$@"
