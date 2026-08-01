#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
ACTION="${1:-help}"
TARGET="${2:-all}"

require_docker() {
  command -v docker >/dev/null 2>&1 || {
    echo "Docker غير مثبت على السيرفر."
    exit 1
  }
}

prepare_runtime_directories() {
  mkdir -p "$SCRIPT_DIR/nginx/generated" "$SCRIPT_DIR/certbot/www" "$SCRIPT_DIR/certbot/conf"
}

# Re-render nginx from the TEMPLATE on every deploy, in whichever mode is
# already in force.
#
# This used to run only when generated/default.conf was missing. That file is
# committed, so it always existed, so the render never ran — and an edit to
# nginx/*.conf.template silently never reached the server. The mode is detected
# rather than assumed because rendering http over a live HTTPS site would
# downgrade it.
ensure_nginx_config() {
  local generated="$SCRIPT_DIR/nginx/generated/default.conf"
  local mode="http"
  if [ -f "$generated" ] && grep -q "listen 443" "$generated"; then
    mode="https"
  fi
  bash "$SCRIPT_DIR/render_nginx_config.sh" "$mode"
}

services_for_target() {
  case "$1" in
    live) echo "redis db_live web_live celery_live nginx" ;;
    dev)  echo "redis db_dev web_dev celery_dev nginx" ;;
    test) echo "redis db_test web_test nginx" ;;
    all)  echo "redis db_live web_live celery_live db_dev web_dev celery_dev db_test web_test nginx" ;;
    *)
      echo "Unknown target: $1" >&2
      exit 1
      ;;
  esac
}

runtime_services_for_target() {
  case "$1" in
    live) echo "redis db_live web_live celery_live" ;;
    dev)  echo "redis db_dev web_dev celery_dev" ;;
    test) echo "redis db_test web_test" ;;
    all)  echo "redis db_live web_live celery_live db_dev web_dev db_test web_test nginx" ;;
    *)
      echo "Unknown target: $1" >&2
      exit 1
      ;;
  esac
}

build_services_for_target() {
  case "$1" in
    live) echo "web_live celery_live" ;;
    dev)  echo "web_dev celery_dev" ;;
    test) echo "web_test" ;;
    all)  echo "web_live celery_live web_dev celery_dev web_test" ;;
    *)
      echo "Unknown target: $1" >&2
      exit 1
      ;;
  esac
}

required_envs_for_target() {
  case "$1" in
    live) echo "live" ;;
    dev) echo "dev" ;;
    test) echo "test" ;;
    all) echo "live dev test" ;;
    *)
      echo "Unknown target: $1" >&2
      exit 1
      ;;
  esac
}

init_env_files() {
  for env_name in live dev test; do
    target_file="$SCRIPT_DIR/env/${env_name}.env"
    example_file="$SCRIPT_DIR/env/${env_name}.env.example"

    if [ ! -f "$target_file" ]; then
      cp "$example_file" "$target_file"
      echo "Created: $target_file"
    else
      echo "Exists: $target_file"
    fi
  done

  echo "راجع الملفات داخل deployment/docker/env/ ثم عدّل كلمات المرور والدومينات قبل التشغيل."
}

assert_env_files_exist() {
  for env_name in $(required_envs_for_target "$1"); do
    target_file="$SCRIPT_DIR/env/${env_name}.env"
    if [ ! -f "$target_file" ]; then
      echo "Missing env file: $target_file"
      echo "شغّل أولاً: bash deployment/docker/deploy.sh init-env"
      exit 1
    fi
  done
}

# Keys added after an environment was first provisioned. An existing env file
# passes the check above while silently missing them, and the application then
# falls back to a default — for PARTNER_DOCS_ROOT that default is INSIDE the
# container filesystem, on no volume, so uploads are destroyed on the next
# rebuild. Fail the deploy instead.
REQUIRED_ENV_KEYS="
PARTNER_DOCS_ROOT
PARTNER_DOC_MAX_FILE_MB
PARTNER_DOC_MAX_TOTAL_MB
PARTNER_DOC_MAX_FILES
PARTNER_APPLICATION_DEDUPE_MINUTES
THROTTLE_PARTNER_APPLICATION
THROTTLE_PUBLIC_CONTACT
THROTTLE_PRICING_CALCULATOR
"

assert_env_keys_present() {
  local failed=0
  for env_name in $(required_envs_for_target "$1"); do
    target_file="$SCRIPT_DIR/env/${env_name}.env"
    for key in $REQUIRED_ENV_KEYS; do
      if ! grep -qE "^[[:space:]]*${key}=" "$target_file"; then
        echo "Missing key '${key}' in ${target_file}"
        failed=1
      fi
    done

    # PARTNER_DOCS_ROOT must never sit under the media root: nginx serves
    # /media/ publicly, and a third party's commercial register must not be
    # downloadable by guessing a URL.
    docs_root="$(grep -E "^[[:space:]]*PARTNER_DOCS_ROOT=" "$target_file" | tail -1 | cut -d= -f2-)"
    case "$docs_root" in
      */media/*|/app/media*)
        echo "REFUSING TO DEPLOY: PARTNER_DOCS_ROOT points inside the public media root"
        echo "  ${target_file}: PARTNER_DOCS_ROOT=${docs_root}"
        failed=1
        ;;
    esac
  done

  if [ "$failed" -ne 0 ]; then
    echo
    echo "أضف المفاتيح الناقصة من deployment/docker/env/*.env.example ثم أعد المحاولة."
    exit 1
  fi
}

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

case "$ACTION" in
  update|deploy)
    # Pull latest git + rebuild + restart  (main deploy command)
    bash "$SCRIPT_DIR/update.sh" "$TARGET"
    ;;
  init-env)
    init_env_files
    ;;
  build)
    require_docker
    assert_env_files_exist "$TARGET"
    assert_env_keys_present "$TARGET"
    prepare_runtime_directories
    ensure_nginx_config
    compose build $(build_services_for_target "$TARGET")
    ;;
  up)
    require_docker
    assert_env_files_exist "$TARGET"
    assert_env_keys_present "$TARGET"
    prepare_runtime_directories
    ensure_nginx_config
    compose up -d --build $(services_for_target "$TARGET")
    ;;
  stop)
    require_docker
    assert_env_files_exist "$TARGET"
    compose stop $(runtime_services_for_target "$TARGET")
    ;;
  restart)
    require_docker
    assert_env_files_exist "$TARGET"
    assert_env_keys_present "$TARGET"
    prepare_runtime_directories
    ensure_nginx_config
    compose restart $(runtime_services_for_target "$TARGET")
    ;;
  logs)
    require_docker
    shift || true
    compose logs -f "$@"
    ;;
  ps)
    require_docker
    compose ps
    ;;
  down)
    require_docker
    compose down
    ;;
  help|--help|-h)
    cat <<'EOF'
Docker deployment helper

Usage:
  bash deployment/docker/deploy.sh update [live|dev|test|all]   ← git pull + rebuild + restart
  bash deployment/docker/deploy.sh deploy [live|dev|test|all]   ← alias for update
  bash deployment/docker/deploy.sh init-env
  bash deployment/docker/deploy.sh build [all|live|dev|test]
  bash deployment/docker/deploy.sh up [all|live|dev|test]
  bash deployment/docker/deploy.sh stop [all|live|dev|test]
  bash deployment/docker/deploy.sh restart [all|live|dev|test]
  bash deployment/docker/deploy.sh logs [service_name]
  bash deployment/docker/deploy.sh ps
  bash deployment/docker/deploy.sh down
EOF
    ;;
  *)
    echo "Unknown action: $ACTION"
    exit 1
    ;;
esac
