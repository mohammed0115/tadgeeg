# Phase 1.1 — Audit Hash Chain
# Adds previous_hash / event_hash / chain_position to InvoiceAuditEvent so the
# chain framework in apps.audit.integrity can detect tampering.
#
# This migration deliberately does NOT touch unrelated model state that was
# auto-detected (constraints/indexes from earlier migrations that drifted).
# Those belong in their own focused migration; mixing them here would make
# rollback risky.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0009_partial_indexes_active_invoices'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoiceauditevent',
            name='previous_hash',
            field=models.CharField(
                blank=True, default='', max_length=64,
                help_text="event_hash of the previous row in this org's chain",
            ),
        ),
        migrations.AddField(
            model_name='invoiceauditevent',
            name='event_hash',
            field=models.CharField(
                blank=True, default='', max_length=64, db_index=True,
                help_text='SHA-256(previous_hash + payload + ts + org)',
            ),
        ),
        migrations.AddField(
            model_name='invoiceauditevent',
            name='chain_position',
            field=models.PositiveBigIntegerField(
                default=0, db_index=True,
                help_text="1-based position within this org's chain",
            ),
        ),
        migrations.AddIndex(
            model_name='invoiceauditevent',
            index=models.Index(
                fields=['invoice', 'chain_position'],
                name='invoice_audit_chain_idx',
            ),
        ),
    ]
