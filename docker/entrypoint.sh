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
    except PermissionError as exc:
        # Not a database problem at all. Django creates MEDIA_ROOT and
        # PARTNER_DOCS_ROOT at import, so a volume owned by root while the
        # container runs as www-data fails here — and used to be reported as
        # "Database unavailable", which is where an hour of the wrong
        # investigation goes. Fail immediately with the real cause.
        print(f"\nPERMISSION ERROR (not a database fault): {exc}", file=sys.stderr)
        print("A mounted volume is not writable by www-data. Fix it with:",
              file=sys.stderr)
        print("  docker compose -f deployment/docker/docker-compose.yml \\",
              file=sys.stderr)
        print("    run --rm -u root web_live chown -R www-data:www-data /app/private_media /app/media",
              file=sys.stderr)
        sys.exit(1)
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

# compilemessages is NOT optional and must not be swallowed.
#
# gettext is installed in this image (see Dockerfile), so a failure here is a
# real failure, not an absent tool. Django loads translations from django.mo at
# process start: if it is missing or older than django.po, ~600 strings render
# in English on an Arabic-first product — silently, with the site up and every
# page subtly wrong. That is worse than a stopped deploy.
python manage.py compilemessages --ignore=.venv || {
  echo "ERROR: compilemessages failed. Arabic would render in English."
  echo "  gettext is expected in this image; check locale/ar/LC_MESSAGES/django.po for syntax errors."
  exit 1
}

python manage.py collectstatic --noinput || { echo "ERROR: collectstatic failed. Check volume permissions: docker compose exec -u root web_live chown -R www-data:www-data /app/staticfiles"; exit 1; }

# ── Catalogue seeding ────────────────────────────────────────────────────────
# Both commands use update_or_create and are safe to re-run. They run only in
# the web container: celery starts from this same entrypoint, and two processes
# seeding the same rows concurrently is a race with no upside.
#
# seed_partners deliberately does NOT re-publish a partner an operator has
# hidden — that is intended behaviour, not a bug to fix here.
# Matched by EXCLUSION, not inclusion. The web services start as
#   sh -c "gunicorn finai_backend.wsgi:application ..."
# so $1 is `sh`, not `gunicorn` — an allow-list of gunicorn/python would have
# matched nothing and silently seeded neither catalogue while looking correct.
case "${1:-}" in
  celery)
    echo "Skipping catalogue seeding in the celery worker (the web container does it)."
    ;;
  *)
    python manage.py seed_billing_plans || {
      echo "ERROR: seed_billing_plans failed — the plan catalogue would be incomplete."
      exit 1
    }
    python manage.py seed_addons || {
      echo "ERROR: seed_addons failed — add-ons would be unbuyable and the"
      echo "       derived savings on /pricing/ would silently disappear."
      exit 1
    }
    python manage.py seed_partners || {
      echo "ERROR: seed_partners failed."
      exit 1
    }
    ;;
esac

exec "$@"
