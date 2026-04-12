"""
Migration 0009: Add partial indexes covering only non-deleted invoices.

Why:
  Full indexes on soft-deleted tables include both live and dead rows.
  Queries that always filter `WHERE is_deleted=FALSE` benefit from a
  partial index that covers only live rows — smaller index, faster scans.

  This is especially impactful for the (organization, status) lookup which
  is the most common filter pattern across invoice list and dashboard views.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0008_invoice_db_constraints"),
    ]

    operations = [
        # Partial index: active invoices by org + status (most frequent filter).
        migrations.AddIndex(
            model_name="invoice",
            index=models.Index(
                fields=["organization", "status"],
                name="invoice_org_status_active",
                condition=models.Q(is_deleted=False),
            ),
        ),
        # Partial index: active invoices by org + risk_level (dashboard tiles).
        migrations.AddIndex(
            model_name="invoice",
            index=models.Index(
                fields=["organization", "risk_level"],
                name="invoice_org_risk_active",
                condition=models.Q(is_deleted=False),
            ),
        ),
        # Partial index: active invoices by org + invoice_date (date-range reports).
        migrations.AddIndex(
            model_name="invoice",
            index=models.Index(
                fields=["organization", "invoice_date"],
                name="invoice_org_date_active",
                condition=models.Q(is_deleted=False),
            ),
        ),
    ]
