"""
Phase 3 — Performance: composite indexes on AuditSession hot query paths.

  Session list: WHERE organization=X ORDER BY created_at DESC  (default ordering)
  Session list: WHERE organization=X AND state=Y              (already covered by
                                                               0004 composite idx)
  Dashboard:    WHERE organization=X AND overall_risk_level=Y
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0004_auditsession_auditfinding_and_more"),
    ]

    operations = [
        # Session list: WHERE org=X ORDER BY created_at DESC
        migrations.AddIndex(
            model_name="auditsession",
            index=models.Index(
                fields=["organization", "-created_at"],
                name="as_org_created_idx",
            ),
        ),
        # Dashboard: WHERE org=X AND overall_risk_level=Y
        migrations.AddIndex(
            model_name="auditsession",
            index=models.Index(
                fields=["organization", "overall_risk_level"],
                name="as_org_risk_idx",
            ),
        ),
    ]
