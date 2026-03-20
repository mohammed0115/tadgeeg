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

  # Fix schema drift: if audit_sessions exists with old schema (session_name instead of name),
  # fake the migrations that already ran so Django doesn't try to recreate them.
  python - <<'PY'
import os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.getenv("DJANGO_SETTINGS_MODULE", "finai_backend.settings"))
import django; django.setup()
from django.db import connection

with connection.cursor() as cur:
    # Check if audit_sessions table has the old 'session_name' column (old schema)
    try:
        cur.execute("SELECT session_name FROM audit_sessions LIMIT 1")
        # Old schema detected — drop and let migration recreate
        print("Old audit_sessions schema detected. Dropping for clean migration...")
        cur.execute("UPDATE invoice_batches SET audit_session_id = NULL WHERE audit_session_id IS NOT NULL")
        cur.execute("DROP TABLE IF EXISTS audit_findings")
        cur.execute("DROP TABLE IF EXISTS audit_sessions")
        # Clear stale migration records
        cur.execute("""
            DELETE FROM django_migrations
            WHERE (app='audit' AND name IN ('0004_auditsession','0005_auditfinding',
                   '0006_rename_audit_findi_organiz_716be4_idx_audit_findi_organiz_dafce2_idx_and_more'))
               OR (app='invoices' AND name='0002_invoice_audit_session_invoicebatch_audit_session')
               OR (app='documents' AND name='0003_document_audit_session')
        """)
        print("Schema drift fixed. Migrations will run cleanly.")
    except Exception:
        # New schema or table doesn't exist — nothing to do
        pass
PY
fi

python manage.py migrate --noinput
python manage.py compilemessages --ignore=.venv || echo "compilemessages skipped (gettext not available)"
python manage.py collectstatic --noinput

exec "$@"
