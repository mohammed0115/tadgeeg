"""
Migration 0008: Add database-level CHECK and UNIQUE constraints to Invoice.

Why:
  The previous schema relied on application-layer validation only. Database
  constraints guarantee invariants even when records are modified directly via
  the ORM, raw SQL, admin imports, or data-migration scripts.

Constraints added:
  - total_amount >= 0        (no negative invoice totals)
  - vat_rate in [0, 100]    (valid percentage range)
  - vat_amount >= 0         (no negative VAT)
  - risk_score in [0, 100]  (bounded scoring range)
  - UNIQUE (organization, invoice_number) WHERE is_deleted=FALSE AND invoice_number != ''
    (blocks duplicate invoice numbers per org at the DB level — backs application rule DUP-001)

Data pre-checks:
  Before adding constraints, existing rows are coerced into valid ranges so the
  migration does not fail on production data that pre-dates these guards.
"""
from django.db import migrations, models


def coerce_existing_rows(apps, schema_editor):
    """Bring any out-of-range values into valid ranges before constraints apply."""
    Invoice = apps.get_model("invoices", "Invoice")

    # Clamp total_amount to >= 0
    Invoice.objects.filter(total_amount__lt=0).update(total_amount=0)

    # Clamp vat_amount to >= 0
    Invoice.objects.filter(vat_amount__lt=0).update(vat_amount=0)

    # Clamp vat_rate to [0, 100]
    Invoice.objects.filter(vat_rate__lt=0).update(vat_rate=0)
    Invoice.objects.filter(vat_rate__gt=100).update(vat_rate=100)

    # Clamp risk_score to [0, 100]
    Invoice.objects.filter(risk_score__lt=0).update(risk_score=0)
    Invoice.objects.filter(risk_score__gt=100).update(risk_score=100)


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0007_validation_result_json_schema"),
    ]

    operations = [
        # 1. Coerce existing data before constraints are enforced.
        migrations.RunPython(coerce_existing_rows, reverse_code=migrations.RunPython.noop),

        # 2. Add CHECK constraints.
        migrations.AddConstraint(
            model_name="invoice",
            constraint=models.CheckConstraint(
                check=models.Q(total_amount__gte=0),
                name="invoice_total_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="invoice",
            constraint=models.CheckConstraint(
                check=models.Q(vat_rate__gte=0) & models.Q(vat_rate__lte=100),
                name="invoice_vat_rate_valid_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="invoice",
            constraint=models.CheckConstraint(
                check=models.Q(vat_amount__gte=0),
                name="invoice_vat_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="invoice",
            constraint=models.CheckConstraint(
                check=models.Q(risk_score__gte=0) & models.Q(risk_score__lte=100),
                name="invoice_risk_score_valid_range",
            ),
        ),

        # 3. Add partial UNIQUE constraint: one invoice_number per org (non-deleted only).
        migrations.AddConstraint(
            model_name="invoice",
            constraint=models.UniqueConstraint(
                fields=["organization", "invoice_number"],
                condition=models.Q(is_deleted=False) & ~models.Q(invoice_number=""),
                name="invoice_unique_number_per_org",
            ),
        ),
    ]
