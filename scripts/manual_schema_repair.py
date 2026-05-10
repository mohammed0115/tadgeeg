"""Manual schema-repair helper — DOES NOT run automatically.

⚠️ DESTRUCTIVE — DROPS TABLES.
=================================================================

This file used to live inline inside `docker/entrypoint.sh`, where it ran on
EVERY container start. That meant a regression in any of the guards below
could blow away production tables on the next deploy. We moved it here so
operators must invoke it deliberately, with a backup taken first.

When to run
-----------
Only when both of these are true:
  1. A previous deploy crashed mid-migration on this MySQL instance, AND
  2. `manage.py migrate` is now failing with "table already exists" or
     "no such column" because a CreateModel ran before a follow-up
     migration that depended on it.

How to run
----------
  # 1. Take a fresh backup. ALWAYS.
  mysqldump -h $DB_HOST -u root -p ... > backup-$(date +%s).sql

  # 2. Dry-run first; reports what *would* be dropped:
  python scripts/manual_schema_repair.py --dry-run

  # 3. If the report looks right, repair (still requires explicit flag):
  python scripts/manual_schema_repair.py --i-have-a-backup

  # 4. Re-run the deploy:
  python manage.py migrate --noinput

What it does
------------
  1. Detects the legacy `audit_sessions.session_name` schema and, if
     present, drops `audit_sessions` + `audit_findings` and clears stale
     django_migrations rows so the new migrations replay cleanly.
  2. Drops orphan tables left behind by failed CreateModel migrations
     (per the ORPHAN_CHECKS table). These checks are conservative — they
     only drop a table if its owning migration row is NOT present in
     django_migrations.

What it WILL NOT do
-------------------
  - It will not run unless `--i-have-a-backup` is passed.
  - It will not run with non-default DJANGO_SETTINGS_MODULE without
     explicit `--allow-non-default-settings`.
  - It will not be auto-invoked by entrypoint.sh / Dockerfile / CI.
"""
from __future__ import annotations

import argparse
import os
import sys

# (app_label, migration_name, [tables to drop if migration not applied])
ORPHAN_CHECKS = [
    ("ledger", "0002_period_close", ["ledger_periods"]),
    (
        "procurement",
        "0001_initial",
        [
            "procurement_threeway_matches",
            "procurement_pr_approvals",
            "procurement_pr_lines",
            "procurement_requisitions",
        ],
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change; do not write.")
    parser.add_argument("--i-have-a-backup", action="store_true",
                        help="Required to actually run destructive operations.")
    parser.add_argument("--allow-non-default-settings", action="store_true",
                        help="Skip the default-settings safety check.")
    args = parser.parse_args()

    if not args.dry_run and not args.i_have_a_backup:
        print("Refusing to run destructive operations without --i-have-a-backup.",
              file=sys.stderr)
        print("Take a mysqldump first, then re-run with the flag.",
              file=sys.stderr)
        return 2

    settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "finai_backend.settings")
    if settings_module != "finai_backend.settings" and not args.allow_non_default_settings:
        print(f"Refusing to run with DJANGO_SETTINGS_MODULE={settings_module}.",
              file=sys.stderr)
        print("Pass --allow-non-default-settings if this is intentional.",
              file=sys.stderr)
        return 2

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "finai_backend.settings")
    import django
    django.setup()
    from django.db import connection

    dry = args.dry_run
    label = "Would" if dry else "Will"
    affected = 0

    with connection.cursor() as cur:
        # ── 1. Legacy audit_sessions schema ──
        try:
            cur.execute("SELECT session_name FROM audit_sessions LIMIT 1")
            print(f"{label} drop legacy audit_sessions / audit_findings tables and "
                  "clear matching django_migrations rows.")
            affected += 1
            if not dry:
                cur.execute(
                    "UPDATE invoice_batches SET audit_session_id = NULL "
                    "WHERE audit_session_id IS NOT NULL"
                )
                cur.execute("DROP TABLE IF EXISTS audit_findings")
                cur.execute("DROP TABLE IF EXISTS audit_sessions")
                cur.execute(
                    """
                    DELETE FROM django_migrations
                    WHERE (app='audit' AND name IN (
                        '0004_auditsession','0005_auditfinding',
                        '0006_rename_audit_findi_organiz_716be4_idx_audit_findi_organiz_dafce2_idx_and_more'))
                       OR (app='invoices' AND name='0002_invoice_audit_session_invoicebatch_audit_session')
                       OR (app='documents' AND name='0003_document_audit_session')
                    """
                )
                print("  ✓ legacy schema cleared")
        except Exception:
            # Either table doesn't exist or column already renamed — nothing to do
            pass

        # ── 2. Orphan tables from failed migrations ──
        for app, migration, tables in ORPHAN_CHECKS:
            cur.execute(
                "SELECT 1 FROM django_migrations WHERE app=%s AND name=%s",
                [app, migration],
            )
            if cur.fetchone():
                continue
            for table in tables:
                cur.execute(
                    "SELECT 1 FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                    [table],
                )
                if cur.fetchone():
                    print(f"{label} drop orphan table `{table}` "
                          f"(from failed prior deploy of {app}.{migration}).")
                    affected += 1
                    if not dry:
                        cur.execute("SET FOREIGN_KEY_CHECKS=0")
                        cur.execute(f"DROP TABLE IF EXISTS `{table}`")
                        cur.execute("SET FOREIGN_KEY_CHECKS=1")

    if affected == 0:
        print("No schema repairs needed — DB is consistent with migrations.")
    elif dry:
        print(f"\nDry run complete. {affected} repair(s) would be performed. "
              "Re-run with --i-have-a-backup to apply.")
    else:
        print(f"\nDone. {affected} repair(s) applied. "
              "Now run: python manage.py migrate --noinput")
    return 0


if __name__ == "__main__":
    sys.exit(main())
