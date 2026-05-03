"""
Tests for Phase 4 — ZATCA Phase 2 integration.

Covers:
  • CSR generation produces a valid PEM with the correct subject + custom OIDs.
  • Fernet round-trip: encrypt → decrypt yields identical bytes.
  • UBL XML generator outputs canonicalisable XML with ZATCA's required
    elements + the PIH chain pointer.
  • TLV QR encodes the 5 mandatory tags + decodes them back.
  • Hash chain: 2 sequential submissions link via invoice_hash → previous_invoice_hash.
  • End-to-end: onboard_egs_device + submit_invoice in mock mode produce a
    cleared submission row with response_payload populated.
  • Rejection translator returns the AR/EN strings the dashboard needs.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.authentication.models import Organization, User
from apps.zatca import crypto as cryp
from apps.zatca import ubl as ubl_gen
from apps.zatca.models import EGSDevice, InvoiceSubmission
from apps.zatca.rejection_codes import seed_rejection_codes, translate_response_errors
from apps.zatca.services import onboard_egs_device, submit_invoice


@pytest.fixture
def org(db):
    return Organization.objects.create(name="ZATCA Test Org")


@pytest.fixture
def user(db, org):
    return User.objects.create_user(
        email="zatca@test.local", full_name="ZATCA Tester",
        password="x", organization=org, role=User.Role.ADMIN,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. CSR + crypto
# ─────────────────────────────────────────────────────────────────────────────

def test_csr_contains_required_subject_and_oids():
    csr_pem, key_pem = cryp.generate_csr_and_key(
        organization_name="Acme KSA",
        organizational_unit="Tadgeeg",
        common_name="1-Acme|2-EGS|3-001",
        serial_number="SN-12345",
        organization_identifier="300000000000003",
        location_address="Riyadh KSA",
    )
    assert csr_pem.startswith(b"-----BEGIN CERTIFICATE REQUEST-----")
    assert key_pem.startswith(b"-----BEGIN PRIVATE KEY-----")

    from cryptography import x509
    csr = x509.load_pem_x509_csr(csr_pem)
    subject_str = csr.subject.rfc4514_string()
    assert "Acme KSA" in subject_str
    assert "Tadgeeg" in subject_str
    assert "1-Acme|2-EGS|3-001" in subject_str
    assert "SN-12345" in subject_str
    # Custom organizationIdentifier OID 2.5.4.97 should be present.
    assert "300000000000003" in subject_str
    # SAN with the ZATCA OIDs.
    san = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    other_oids = {o.type_id.dotted_string for o in san if isinstance(o, x509.OtherName)}
    assert {"1.3.6.1.4.1.311.20.2.3", "1.3.6.1.4.1.311.20.2.6"} <= other_oids


def test_fernet_round_trip(settings):
    settings.ZATCA_FERNET_KEY = ""  # use the SECRET_KEY-derived fallback
    plaintext = b"super-secret-private-key"
    enc = cryp.encrypt_secret(plaintext)
    assert enc != plaintext
    assert cryp.decrypt_secret(enc) == plaintext


def test_canonicalise_yields_stable_bytes():
    xml = "<?xml version=\"1.0\"?><root><a>1</a></root>"
    a = cryp.canonicalise_xml(xml)
    b = cryp.canonicalise_xml(xml)
    assert a == b
    assert cryp.hash_invoice_xml(xml) == cryp.hash_invoice_xml(xml)


# ─────────────────────────────────────────────────────────────────────────────
# 2. UBL + TLV QR
# ─────────────────────────────────────────────────────────────────────────────

def test_ubl_renders_required_elements():
    payload = ubl_gen.InvoicePayload(
        uuid=str(uuid.uuid4()),
        invoice_number="INV-100",
        issue_date=datetime(2026, 5, 1, 12, 0, 0),
        invoice_type_code="0100",
        seller_name="Acme KSA", seller_vat_number="300000000000003",
        buyer_name="Buyer Co",   buyer_vat_number="300000000000007",
        line_extension_total=Decimal("1000"),
        tax_exclusive_total=Decimal("1000"),
        tax_inclusive_total=Decimal("1150"),
        vat_amount=Decimal("150"),
        lines=[ubl_gen.InvoiceLine(
            line_id="1", description="Service", quantity=Decimal("1"),
            unit_price=Decimal("1000"), line_total=Decimal("1000"),
            vat_rate=Decimal("15"), vat_amount=Decimal("150"),
        )],
        previous_invoice_hash="a" * 64,
    )
    xml = ubl_gen.render_invoice_xml(payload)
    for needle in ["<Invoice", "<cbc:UUID>", "<cbc:IssueDate>2026-05-01",
                   "<cbc:InvoiceTypeCode", "PIH", "Acme KSA", "Buyer Co"]:
        assert needle in xml, f"missing: {needle}"


def test_tlv_qr_encodes_5_mandatory_tags_and_decodes():
    payload = ubl_gen.build_tlv_qr(
        seller_name="Acme KSA", seller_vat="300000000000003",
        timestamp=datetime(2026, 5, 1, 12, 0, 0),
        invoice_total=Decimal("1150.00"), vat_total=Decimal("150.00"),
    )
    decoded = ubl_gen.decode_tlv_qr(payload)
    tags = {row["tag"] for row in decoded}
    assert {1, 2, 3, 4, 5} == tags
    # Tag 1 is seller name.
    seller = next(r for r in decoded if r["tag"] == 1)
    assert seller["value"] == b"Acme KSA"


def test_tlv_qr_with_hash_and_signature_includes_extra_tags():
    payload = ubl_gen.build_tlv_qr(
        seller_name="X", seller_vat="300000000000003",
        timestamp=datetime(2026, 5, 1, 12, 0, 0),
        invoice_total=Decimal("100"), vat_total=Decimal("15"),
        invoice_hash="aa" * 32,
        stamp_signature_b64=base64.b64encode(b"stamp-sig").decode("ascii"),
    )
    tags = {row["tag"] for row in ubl_gen.decode_tlv_qr(payload)}
    assert {1, 2, 3, 4, 5, 6, 7} <= tags


# ─────────────────────────────────────────────────────────────────────────────
# 3. End-to-end (mock mode)
# ─────────────────────────────────────────────────────────────────────────────

def test_onboard_egs_device_completes_via_mock(db, org, settings):
    settings.ZATCA_LIVE_MODE = False
    device = onboard_egs_device(
        organization=org,
        common_name="1-Tadgeeg|2-EGS|3-001",
        serial_number="SN-001",
        organization_identifier="300000000000003",
    )
    assert device.status == EGSDevice.Status.COMPLIANCE
    assert device.csid_secret_encrypted   # mock returned a fake secret
    assert device.private_key_encrypted   # we encrypted the generated key
    assert device.csr_pem.startswith("-----BEGIN CERTIFICATE REQUEST-----")
    # Decrypt round-trip works.
    pem = cryp.decrypt_secret(device.private_key_encrypted)
    assert pem.startswith(b"-----BEGIN PRIVATE KEY-----")


def test_submit_invoice_creates_cleared_submission(db, org, user, settings):
    settings.ZATCA_LIVE_MODE = False
    onboard_egs_device(
        organization=org, common_name="1-Tadgeeg|2-EGS|3-001",
        serial_number="SN-001", organization_identifier="300000000000003",
    )
    from apps.invoices.models import Invoice
    inv = Invoice.objects.create(
        organization=org, uploaded_by=user,
        invoice_number="ZATCA-1", vendor_name="Vendor X",
        customer_name="Buyer Co", customer_vat_number="300000000000007",
        currency="SAR",
        subtotal=Decimal("1000"), vat_amount=Decimal("150"), vat_rate=Decimal("15"),
        total_amount=Decimal("1150"),
        invoice_date=timezone.now().date(),
        original_filename="x.pdf",
        line_items=[{"description": "Service", "quantity": 1,
                     "unit_price": 1000, "total": 1000,
                     "vat_rate": 15, "vat_amount": 150}],
    )

    sub = submit_invoice(inv, mode=InvoiceSubmission.SubmissionType.CLEARANCE)
    assert sub.status == InvoiceSubmission.Status.CLEARED
    assert sub.invoice_hash and len(sub.invoice_hash) == 64
    assert sub.qr_tlv_base64
    assert sub.cleared_xml   # mock echoes the signed XML
    assert sub.previous_invoice_hash == ""   # first in chain
    assert sub.chain_position == 1


def test_two_submissions_chain_via_pih(db, org, user, settings):
    settings.ZATCA_LIVE_MODE = False
    onboard_egs_device(
        organization=org, common_name="1-Tadgeeg|2-EGS|3-001",
        serial_number="SN-001", organization_identifier="300000000000003",
    )
    from apps.invoices.models import Invoice
    inv1 = Invoice.objects.create(
        organization=org, uploaded_by=user,
        invoice_number="A1", vendor_name="V1", currency="SAR",
        subtotal=Decimal("100"), vat_amount=Decimal("15"), total_amount=Decimal("115"),
        invoice_date=timezone.now().date(), original_filename="x.pdf",
    )
    inv2 = Invoice.objects.create(
        organization=org, uploaded_by=user,
        invoice_number="A2", vendor_name="V2", currency="SAR",
        subtotal=Decimal("200"), vat_amount=Decimal("30"), total_amount=Decimal("230"),
        invoice_date=timezone.now().date(), original_filename="y.pdf",
    )
    s1 = submit_invoice(inv1, mode=InvoiceSubmission.SubmissionType.CLEARANCE)
    s2 = submit_invoice(inv2, mode=InvoiceSubmission.SubmissionType.CLEARANCE)
    assert s1.chain_position == 1
    assert s2.chain_position == 2
    assert s2.previous_invoice_hash == s1.invoice_hash


# ─────────────────────────────────────────────────────────────────────────────
# 4. Rejection translator
# ─────────────────────────────────────────────────────────────────────────────

def test_seed_rejection_codes_is_idempotent(db):
    a = seed_rejection_codes()
    b = seed_rejection_codes()
    assert a > 0
    assert b == 0   # second call is a no-op


def test_translate_response_errors_returns_localised_text(db):
    seed_rejection_codes()
    out = translate_response_errors(
        [{"code": "BR-KSA-09", "message": "Invalid VAT"}],
        lang="en",
    )
    assert out[0]["title"]
    assert "VAT" in out[0]["title"] or "trn" in out[0]["title"].lower()
    assert out[0]["fix_hint"]


def test_translate_response_errors_handles_unknown_code(db):
    seed_rejection_codes()
    out = translate_response_errors(
        [{"code": "ZZZ-99", "message": "Mystery"}], lang="ar",
    )
    assert out[0]["code"] == "ZZZ-99"
    assert out[0]["title"] == ""   # no match — empty translated fields
    assert out[0]["raw_message"] == "Mystery"


# ─────────────────────────────────────────────────────────────────────────────
# 5. API
# ─────────────────────────────────────────────────────────────────────────────

def test_dashboard_endpoint_returns_readiness_checklist(db, user, settings):
    settings.ZATCA_LIVE_MODE = False
    from rest_framework.test import APIClient
    c = APIClient(); c.force_authenticate(user)
    r = c.get("/api/v1/zatca/dashboard/")
    assert r.status_code == 200
    data = r.json()
    assert "counts" in data
    assert "readiness" in data
    assert len(data["readiness"]) >= 4
    # Initial state — no devices, no cleared invoices → most checks fail.
    assert any(item["ok"] is False for item in data["readiness"])


def test_submission_api_requires_admin(db, settings, org):
    settings.ZATCA_LIVE_MODE = False
    junior = User.objects.create_user(
        email="zat-junior@test.local", full_name="Junior", password="x",
        organization=org, role=User.Role.JUNIOR_AUDITOR,
    )
    from rest_framework.test import APIClient
    c = APIClient(); c.force_authenticate(junior)
    r = c.post("/api/v1/zatca/submissions/submit/", {"invoice_id": "x"}, format="json")
    assert r.status_code == 403
