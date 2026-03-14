#!/bin/sh
set -e

cd /app

if [ "${DB_ENGINE:-}" = "django.db.backends.mysql" ] || [ -n "${DB_HOST:-}" ]; then
  echo "Waiting for MySQL to become available..."

  python - <<'PY'
import os
import sys
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.getenv("DJANGO_SETTINGS_MODULE", "finai_backend.settings"))

last_error = None
deadline = time.time() + 180

while time.time() < deadline:
    try:
        import django
        django.setup()
        from django.db import connections
        connections["default"].ensure_connection()
        print("MySQL is ready.")
        break
    except Exception as exc:
        last_error = exc
        print(f"Database unavailable: {exc}")
        time.sleep(3)
else:
    print(f"Could not connect to database: {last_error}", file=sys.stderr)
    sys.exit(1)
PY
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
