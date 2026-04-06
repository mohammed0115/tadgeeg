"""
Migration: Add composite database indexes on VendorProfile for the
most common query patterns used by the Vendor Intelligence system.

Index strategy
--------------
  (organization, risk_tier)          → list_by_org(risk_tier=…) and high_risk()
  (organization, is_approved)        → unapproved vendor reports
  (organization, is_new)             → new vendor detection
  (organization, risk_score desc)    → top_risky() and dashboard ordering
  (organization, compliance_issue_count desc)  → compliance reports
  (organization, transaction_frequency_30d)    → frequency spike detection

All indexes are prefixed with ``vi_`` to namespace them.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0005_vendor_intelligence_fields"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="vendorprofile",
            index=models.Index(
                fields=["organization", "risk_tier"],
                name="vi_org_risk_tier_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="vendorprofile",
            index=models.Index(
                fields=["organization", "is_approved"],
                name="vi_org_approved_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="vendorprofile",
            index=models.Index(
                fields=["organization", "is_new"],
                name="vi_org_is_new_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="vendorprofile",
            index=models.Index(
                fields=["organization", "-risk_score"],
                name="vi_org_risk_score_desc_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="vendorprofile",
            index=models.Index(
                fields=["organization", "-compliance_issue_count"],
                name="vi_org_compliance_desc_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="vendorprofile",
            index=models.Index(
                fields=["organization", "-transaction_frequency_30d"],
                name="vi_org_frequency_desc_idx",
            ),
        ),
    ]
