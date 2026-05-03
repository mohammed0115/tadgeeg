"""
ZATCA orchestration — Phase 4.

Two end-to-end flows:

  • ``onboard_egs_device(...)`` — create CSR + key, store encrypted, request
    a sandbox CSID via ZATCAClient, persist the cert and the CSID secret.
  • ``submit_invoice(invoice, mode='clearance'|'reporting')`` — pick the latest
    PIH, build the UBL XML, hash + sign it, build the TLV QR, push to
    ZATCAClient, persist the InvoiceSubmission row with the response.

Both are pure orchestration — the heavy lifting is in `crypto.py`,
`ubl.py`, and `client.py`.
"""

from __future__ import annotations

import base64
import logging
import uuid as _uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from apps.zatca import crypto as cryp
from apps.zatca import ubl as ubl_gen
from apps.zatca.client import ZATCAClient, ZATCAResponse
from apps.zatca.models import EGSDevice, InvoiceSubmission

logger = logging.getLogger("finai.zatca")


# ─────────────────────────────────────────────────────────────────────────────
# Device onboarding
# ─────────────────────────────────────────────────────────────────────────────

def onboard_egs_device(
    *,
    organization,
    common_name: str,
    serial_number: str,
    organization_identifier: str,
    organizational_unit: str = "Tadgeeg",
    branch_name: str = "",
    environment: str = EGSDevice.Environment.SANDBOX,
    location_address: str = "",
    industry: str = "Audit Software",
    otp: str = "123456",
    is_production: bool = False,
) -> EGSDevice:
    """One-shot onboarding — creates a row in the desired environment.

    The OTP is provided by the ZATCA Fatoora portal during EGS registration.
    In live mode the call hits ``/compliance``; in mock mode it returns a
    deterministic fake CSID so the rest of the pipeline can still run.
    """
    csr_pem, key_pem = cryp.generate_csr_and_key(
        organization_name=organization.name,
        organizational_unit=organizational_unit,
        common_name=common_name,
        serial_number=serial_number,
        organization_identifier=organization_identifier,
        location_address=location_address,
        industry=industry,
        is_production=is_production,
    )

    encrypted_key = cryp.encrypt_secret(key_pem)

    device = EGSDevice.objects.create(
        organization=organization,
        common_name=common_name,
        serial_number=serial_number,
        branch_name=branch_name,
        environment=environment,
        csr_pem=csr_pem.decode("utf-8"),
        private_key_encrypted=encrypted_key,
        status=EGSDevice.Status.CSR_READY,
    )

    # Hand the CSR to the Fatoora compliance endpoint.
    client = ZATCAClient(environment=environment)
    resp = client.request_compliance_csid(csr_pem, otp=otp)
    return _apply_csid_response(device, resp)


def renew_egs_device(device: EGSDevice, *,
                     compliance_request_id: Optional[str] = None) -> EGSDevice:
    """Exchange the compliance request for a production CSID, or refresh
    the cert when ``valid_until`` is < 30 days away."""
    client = ZATCAClient(environment=device.environment,
                         certificate_pem=device.certificate_pem.encode("utf-8") if device.certificate_pem else None,
                         csid_secret=cryp.decrypt_secret(device.csid_secret_encrypted) if device.csid_secret_encrypted else None)

    if compliance_request_id:
        resp = client.request_production_csid(compliance_request_id)
    else:
        # Same endpoint as onboarding — ZATCA accepts the existing CSR.
        resp = client.request_compliance_csid(
            device.csr_pem.encode("utf-8"), otp="000000",
        )
    return _apply_csid_response(device, resp, mark_renewed=True)


def _apply_csid_response(device: EGSDevice, resp: ZATCAResponse,
                         *, mark_renewed: bool = False) -> EGSDevice:
    if not resp.ok:
        device.status = EGSDevice.Status.PENDING
        device.save(update_fields=["status", "updated_at"])
        return device

    raw = resp.raw or {}
    cert_b64 = raw.get("binarySecurityToken") or ""
    secret   = raw.get("secret") or ""

    if cert_b64:
        try:
            cert_pem = base64.b64decode(cert_b64).decode("utf-8")
            device.certificate_pem = cert_pem
            try:
                not_before, not_after = cryp.cert_validity_dates(cert_pem.encode("utf-8"))
                device.valid_from = not_before
                device.valid_until = not_after
            except Exception:
                # Mock cert won't parse — fall back to a 1-year window.
                device.valid_from  = timezone.now()
                device.valid_until = timezone.now() + _one_year()
        except Exception as exc:
            logger.warning("[zatca.services] cert decode failed: %s", exc)

    if secret:
        device.csid_secret_encrypted = cryp.encrypt_secret(secret.encode("utf-8"))

    device.status = (EGSDevice.Status.ACTIVE if device.environment == EGSDevice.Environment.PRODUCTION
                     else EGSDevice.Status.COMPLIANCE)
    if mark_renewed:
        device.last_renewed_at = timezone.now()
    device.save()
    return device


def _one_year():
    from datetime import timedelta
    return timedelta(days=365)


# ─────────────────────────────────────────────────────────────────────────────
# Submission
# ─────────────────────────────────────────────────────────────────────────────

def submit_invoice(
    invoice,
    *,
    mode: str = InvoiceSubmission.SubmissionType.CLEARANCE,
    egs_device: Optional[EGSDevice] = None,
) -> InvoiceSubmission:
    """End-to-end submission for one Invoice instance.

    Steps:
      1. Pick the active EGS device (org-scoped).
      2. Look up the previous-invoice-hash (last submission in the org's chain).
      3. Render UBL → hash → sign → encode TLV QR.
      4. Call ZATCAClient.clear_invoice (B2B) or report_invoice (B2C).
      5. Persist InvoiceSubmission with the response.

    The returned ``InvoiceSubmission`` carries the cleared XML, status, error
    list, and chain pointers — ready for the dashboard to read.
    """
    org = invoice.organization

    if egs_device is None:
        egs_device = (
            EGSDevice.objects.filter(
                organization=org,
                status__in=[EGSDevice.Status.ACTIVE, EGSDevice.Status.COMPLIANCE],
            )
            .order_by("-updated_at").first()
        )

    submission = InvoiceSubmission.objects.create(
        organization=org,
        egs_device=egs_device,
        invoice=invoice,
        zatca_uuid=_uuid.uuid4(),
        submission_type=mode,
        status=InvoiceSubmission.Status.DRAFT,
    )

    # 1. Find the previous PIH for this org's chain.
    last = (
        InvoiceSubmission.objects
        .filter(organization=org)
        .exclude(pk=submission.pk)
        .filter(status__in=[InvoiceSubmission.Status.CLEARED,
                            InvoiceSubmission.Status.REPORTED,
                            InvoiceSubmission.Status.WARNING])
        .order_by("-chain_position", "-created_at")
        .first()
    )
    submission.previous_invoice_hash = last.invoice_hash if last else ""
    submission.chain_position        = (last.chain_position + 1) if last else 1

    # 2. Build payload + render XML.
    payload = _payload_from_invoice(invoice, submission)
    xml = ubl_gen.render_invoice_xml(payload)
    submission.xml_unsigned = xml

    # 3. Hash + sign.
    invoice_hash = cryp.hash_invoice_xml(xml)
    submission.invoice_hash = invoice_hash

    signature_b64 = ""
    pub_pem = b""
    if egs_device and egs_device.private_key_encrypted:
        try:
            key_pem = cryp.decrypt_secret(egs_device.private_key_encrypted)
            signature_b64 = cryp.stamp_payload(key_pem,
                                               cryp.canonicalise_xml(xml))
            pub_pem = cryp.public_key_pem_from_private(key_pem)
        except Exception as exc:
            logger.warning("[zatca.services] sign failed: %s", exc)

    # Inline the stamp + chain pointer into the signed XML so cleared_xml
    # round-trips it. Real production XMLs use a UBL signature block; we
    # append a comment for legibility — this is byte-identical to xml_unsigned
    # under canonicalisation, since lxml strips comments.
    signed_xml = xml.replace(
        "</Invoice>",
        f"  <!-- ZATCA invoice_hash={invoice_hash} signature={signature_b64[:24]}... -->\n</Invoice>",
    )
    submission.xml_signed = signed_xml
    submission.status     = InvoiceSubmission.Status.SIGNED

    # 4. TLV QR.
    submission.qr_tlv_base64 = ubl_gen.build_tlv_qr(
        seller_name=payload.seller_name,
        seller_vat=payload.seller_vat_number,
        timestamp=payload.issue_date,
        invoice_total=payload.tax_inclusive_total,
        vat_total=payload.vat_amount,
        invoice_hash=invoice_hash,
        stamp_signature_b64=signature_b64,
        public_key_pem=pub_pem,
    )

    # 5. Push to Fatoora.
    cert_pem = (egs_device.certificate_pem or "").encode("utf-8") if egs_device else b""
    csid_secret = (cryp.decrypt_secret(egs_device.csid_secret_encrypted)
                   if egs_device and egs_device.csid_secret_encrypted else b"")
    client = ZATCAClient(
        environment=(egs_device.environment if egs_device else EGSDevice.Environment.SANDBOX),
        certificate_pem=cert_pem, csid_secret=csid_secret,
    )

    submission.submitted_at = timezone.now()
    submission.status = InvoiceSubmission.Status.SUBMITTED

    if mode == InvoiceSubmission.SubmissionType.CLEARANCE:
        resp = client.clear_invoice(
            signed_xml=signed_xml, invoice_uuid=str(submission.zatca_uuid),
            invoice_hash=invoice_hash,
        )
    else:
        resp = client.report_invoice(
            signed_xml=signed_xml, invoice_uuid=str(submission.zatca_uuid),
            invoice_hash=invoice_hash,
        )

    _persist_response(submission, resp, mode)
    return submission


def _persist_response(submission: InvoiceSubmission,
                      resp: ZATCAResponse, mode: str) -> None:
    submission.response_code     = resp.code
    submission.response_status   = resp.status
    submission.response_warnings = resp.warnings
    submission.response_errors   = resp.errors
    submission.response_payload  = resp.raw
    submission.cleared_xml       = resp.cleared_xml or ""

    if not resp.ok:
        submission.status = InvoiceSubmission.Status.REJECTED
    elif resp.warnings:
        submission.status = InvoiceSubmission.Status.WARNING
        submission.cleared_at = timezone.now()
    elif mode == InvoiceSubmission.SubmissionType.CLEARANCE:
        submission.status = InvoiceSubmission.Status.CLEARED
        submission.cleared_at = timezone.now()
    else:
        submission.status = InvoiceSubmission.Status.REPORTED
        submission.cleared_at = timezone.now()

    submission.save()


# ─────────────────────────────────────────────────────────────────────────────
# Invoice → InvoicePayload mapping
# ─────────────────────────────────────────────────────────────────────────────

def _payload_from_invoice(invoice, submission: InvoiceSubmission
                          ) -> ubl_gen.InvoicePayload:
    org = invoice.organization
    items = invoice.line_items or []
    lines = []
    for idx, li in enumerate(items, start=1):
        if not isinstance(li, dict):
            continue
        qty   = Decimal(str(li.get("quantity") or li.get("qty") or 1))
        price = Decimal(str(li.get("unit_price") or li.get("price") or 0))
        total = Decimal(str(li.get("total") or li.get("line_total") or qty * price))
        vatp  = Decimal(str(li.get("vat_rate") or invoice.vat_rate or 15))
        vata  = Decimal(str(li.get("vat_amount") or (total * vatp / 100)))
        lines.append(ubl_gen.InvoiceLine(
            line_id=str(idx),
            description=str(li.get("description") or li.get("name") or "Item"),
            quantity=qty, unit_price=price, line_total=total,
            vat_rate=vatp, vat_amount=vata,
        ))

    issue_dt = (
        datetime.combine(invoice.invoice_date, datetime.min.time())
        if invoice.invoice_date else datetime.utcnow()
    )

    inv_type_code = ("0100"
                     if submission.submission_type == InvoiceSubmission.SubmissionType.CLEARANCE
                     else "0200")

    return ubl_gen.InvoicePayload(
        uuid=str(submission.zatca_uuid),
        invoice_number=invoice.invoice_number or str(invoice.id)[:8],
        issue_date=issue_dt,
        invoice_type_code=inv_type_code,
        currency=invoice.currency or "SAR",

        seller_name=org.name,
        seller_vat_number=getattr(org, "vat_number", "") or "",
        seller_cr_number=getattr(org, "cr_number", "") or "",
        seller_address=getattr(org, "address", "") or "",

        buyer_name=invoice.customer_name or invoice.vendor_name or "",
        buyer_vat_number=invoice.customer_vat_number or "",
        buyer_address="",

        line_extension_total=Decimal(str(invoice.subtotal or 0)),
        tax_exclusive_total=Decimal(str(invoice.subtotal or 0)),
        tax_inclusive_total=Decimal(str(invoice.total_amount or 0)),
        vat_amount=Decimal(str(invoice.vat_amount or 0)),
        payable_amount=Decimal(str(invoice.total_amount or 0)),

        lines=lines,
        previous_invoice_hash=submission.previous_invoice_hash,
    )
