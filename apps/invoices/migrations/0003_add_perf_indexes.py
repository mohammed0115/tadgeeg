"""
Phase 3 — Performance: composite indexes on Invoice hot query paths.

Existing single-column indexes (risk_level, is_duplicate) are superseded by
composites that also filter on organization, which is always present in
multi-tenant API queries.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0002_invoicebatch_audit_session"),
    ]

    operations = [
        # Dashboard: WHERE org=X AND risk_level IN ('high','critical')
        migrations.AddIndex(
            model_name="invoice",
            index=models.Index(
                fields=["organization", "risk_level"],
                name="inv_org_risk_idx",
            ),
        ),
        # Duplicate review: WHERE org=X AND is_duplicate=True
        migrations.AddIndex(
            model_name="invoice",
            index=models.Index(
                fields=["organization", "is_duplicate"],
                name="inv_org_dup_idx",
            ),
        ),
        # Default list ordering: WHERE org=X ORDER BY created_at DESC
        migrations.AddIndex(
            model_name="invoice",
            index=models.Index(
                fields=["organization", "-created_at"],
                name="inv_org_created_idx",
            ),
        ),
    ]
