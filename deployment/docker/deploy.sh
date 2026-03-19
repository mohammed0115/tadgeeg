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

ensure_nginx_config() {
  if [ ! -f "$SCRIPT_DIR/nginx/generated/default.conf" ]; then
    bash "$SCRIPT_DIR/render_nginx_config.sh" http
  fi
}

services_for_target() {
  case "$1" in
    live) echo "db_live web_live nginx" ;;
    dev) echo "db_dev web_dev nginx" ;;
    test) echo "db_test web_test nginx" ;;
    all) echo "db_live web_live db_dev web_dev db_test web_test nginx" ;;
    *)
      echo "Unknown target: $1" >&2
      exit 1
      ;;
  esac
}

runtime_services_for_target() {
  case "$1" in
    live) echo "db_live web_live" ;;
    dev) echo "db_dev web_dev" ;;
    test) echo "db_test web_test" ;;
    all) echo "db_live web_live db_dev web_dev db_test web_test nginx" ;;
    *)
      echo "Unknown target: $1" >&2
      exit 1
      ;;
  esac
}

build_services_for_target() {
  case "$1" in
    live) echo "web_live" ;;
    dev) echo "web_dev" ;;
    test) echo "web_test" ;;
    all) echo "web_live web_dev web_test" ;;
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
    prepare_runtime_directories
    ensure_nginx_config
    compose build $(build_services_for_target "$TARGET")
    ;;
  up)
    require_docker
    assert_env_files_exist "$TARGET"
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
