"""Run the invoice-to-Document bridge backfill missed by the original 0017.

Some environments applied the earlier version of 0017 before its conservative
backfill was restored.  Django never reruns an applied migration, so this
migration deliberately invokes the restored 0017 routine exactly once on those
environments.  The operation only fills a NULL bridge for an unambiguous,
same-organisation Document match; it never creates a synthetic Document and
never overwrites an existing bridge.
"""

from importlib import import_module

from django.db import migrations


def apply_missed_audit_document_backfill(apps, schema_editor):
    """Execute the restored 0017 backfill on databases that already recorded it."""
    migration_0017 = import_module(
        "apps.invoices.migrations.0017_invoice_audit_document"
    )
    migration_0017.backfill_audit_document(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [
        ("invoices", "0017_invoice_audit_document"),
    ]

    operations = [
        migrations.RunPython(
            apply_missed_audit_document_backfill,
            migrations.RunPython.noop,
        ),
    ]
