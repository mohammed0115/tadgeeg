# Generated manually for the invoice quota/audit identity bridge.

import logging

from django.db import migrations, models


logger = logging.getLogger(__name__)


def backfill_audit_document(apps, schema_editor):
    """Link only invoices whose legacy Document identity is unambiguous.

    Older invoice uploads did not persist the Document bridge.  The backfill
    therefore never creates a synthetic Document and never guesses across
    organisations.  An exact match is limited to the same organisation,
    invoice document type, filename, file size and (where available) session
    and uploader.  Anything else stays NULL and is counted for follow-up.
    """
    Invoice = apps.get_model("invoices", "Invoice")
    Document = apps.get_model("documents", "Document")

    total = filled = no_candidate = ambiguous = 0
    for invoice in Invoice.objects.filter(audit_document__isnull=True).iterator():
        total += 1
        if not invoice.original_filename or not invoice.file_size:
            no_candidate += 1
            continue

        candidates = Document.objects.filter(
            organization_id=invoice.organization_id,
            document_type="invoice",
            original_filename=invoice.original_filename,
            file_size=invoice.file_size,
        )
        if invoice.audit_session_id:
            candidates = candidates.filter(audit_session_id=invoice.audit_session_id)
        if invoice.uploaded_by_id:
            candidates = candidates.filter(uploaded_by_id=invoice.uploaded_by_id)

        document_ids = list(candidates.values_list("pk", flat=True)[:2])
        if len(document_ids) == 1:
            Invoice.objects.filter(pk=invoice.pk, audit_document__isnull=True).update(
                audit_document_id=document_ids[0]
            )
            filled += 1
        elif not document_ids:
            no_candidate += 1
        else:
            ambiguous += 1

    logger.info(
        "0017 invoice audit-document backfill: total=%s filled=%s "
        "left_null_no_candidate=%s left_null_ambiguous=%s",
        total,
        filled,
        no_candidate,
        ambiguous,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0013_canonical_data_organization"),
        ("invoices", "0016_chain_partition_and_fork_constraint"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="audit_document",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="+",
                to="documents.document",
            ),
        ),
        migrations.RunPython(backfill_audit_document, migrations.RunPython.noop),
    ]
