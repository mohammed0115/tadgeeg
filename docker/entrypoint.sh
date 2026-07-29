#!/bin/sh
set -e

# Tadgeeg container entrypoint.
#
# Safe-by-default:
#   1. Wait for MySQL.
#   2. Run migrations.
#   3. Compile messages and collect static.
#   4. Exec the requested command (gunicorn / celery / etc.).
#
# It does NOT drop tables, it does NOT mutate django_migrations rows,
# and it does NOT auto-repair schema drift. If a previous deploy crashed
# mid-migration and the DB is in an inconsistent state, an operator must
# invoke `python scripts/manual_schema_repair.py` deliberately, after
# taking a backup. Auto-running destructive SQL on every container
# restart is a foot-gun (one accidental change to a guard = data loss).

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

# --fake-initial: create tables on a fresh DB, or mark an initial migration as
# applied when its tables already exist (safe when an app was just added to
# INSTALLED_APPS but its tables pre-exist from a legacy state). Prevents both
# "table doesn't exist" (fresh) and "table already exists" (legacy) on deploy.
python manage.py migrate --noinput --fake-initial
python manage.py compilemessages --ignore=.venv || echo "compilemessages skipped (gettext not available)"
python manage.py collectstatic --noinput || { echo "ERROR: collectstatic failed. Check volume permissions: docker compose exec -u root web_live chown -R www-data:www-data /app/staticfiles"; exit 1; }

exec "$@"
