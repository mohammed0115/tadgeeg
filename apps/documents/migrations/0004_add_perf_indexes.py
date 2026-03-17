"""
Phase 3 — Performance: composite indexes on hot query paths.

These indexes target the most common filter + order combinations seen in
the document list, pipeline health check, and cross-session duplicate queries.

All new indexes use database-level names (unique within the table) to avoid
Django's generated name collisions on MySQL where the index prefix limit is 64 chars.

Production note:
  On a live MySQL table with millions of rows, create these indexes using
  pt-online-schema-change or gh-ost to avoid table locks, e.g.:
    pt-online-schema-change --alter "ADD INDEX ..." D=finai_live,t=documents
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0003_document_state_history"),
    ]

    operations = [
        # ── documents table ────────────────────────────────────────────────────
        # Document list: WHERE org=X AND status=Y  (most common API filter combo)
        migrations.AddIndex(
            model_name="document",
            index=models.Index(
                fields=["organization", "processing_status"],
                name="doc_org_status_idx",
            ),
        ),
        # Document list: WHERE org=X ORDER BY created_at DESC  (default ordering)
        migrations.AddIndex(
            model_name="document",
            index=models.Index(
                fields=["organization", "-created_at"],
                name="doc_org_created_idx",
            ),
        ),
        # Document list: WHERE org=X AND document_type=Y
        migrations.AddIndex(
            model_name="document",
            index=models.Index(
                fields=["organization", "document_type"],
                name="doc_org_type_idx",
            ),
        ),

        # ── document_analysis_results table ───────────────────────────────────
        # Cross-session dup S2: WHERE org + vendor_name + document_number + amount
        migrations.AddIndex(
            model_name="documentanalysisresult",
            index=models.Index(
                fields=["vendor_name", "document_number"],
                name="dar_vendor_docnum_idx",
            ),
        ),
        # Cross-session dup S4: WHERE org + total_amount + doc_date
        migrations.AddIndex(
            model_name="documentanalysisresult",
            index=models.Index(
                fields=["total_amount", "doc_date"],
                name="dar_amount_date_idx",
            ),
        ),
        # Dashboard: WHERE org + risk_level (high-risk document count)
        migrations.AddIndex(
            model_name="documentanalysisresult",
            index=models.Index(
                fields=["risk_level", "is_duplicate"],
                name="dar_risk_dup_idx",
            ),
        ),
        # Reprocess task: WHERE org + risk_level IN ('high','critical')
        migrations.AddIndex(
            model_name="documentanalysisresult",
            index=models.Index(
                fields=["risk_level", "requires_review"],
                name="dar_risk_review_idx",
            ),
        ),
    ]
