import pytest


@pytest.mark.django_db
def test_duplicate_detector_excludes_the_persisted_invoice_it_is_analysing():
    from apps.authentication.models import Organization
    from apps.invoices.models import Invoice
    from core.services.detection.duplicate_detector import DuplicateDetector

    organization = Organization.objects.create(name="Duplicate guard", name_ar="تكرار")
    invoice = Invoice.objects.create(
        organization=organization,
        invoice_number="SELF-001",
        vendor_name="Self Exclusion Supplier",
        original_filename="self.pdf",
    )
    detector = DuplicateDetector(organization_id=organization.id)

    self_result = detector.detect(
        {
            "invoice_id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "vendor_name": invoice.vendor_name,
        }
    )
    external_result = detector.detect(
        {
            "invoice_number": invoice.invoice_number,
            "vendor_name": invoice.vendor_name,
        }
    )

    assert self_result["is_duplicate"] is False
    assert self_result["matched_document_ids"] == []
    assert external_result["is_duplicate"] is True
    assert str(invoice.id) in {str(match) for match in external_result["matched_document_ids"]}
