"""
Tests for Phase 7.3 — Procurement workflow.

Covers:
  • create_requisition computes total_amount from lines (anti-fraud).
  • submit_for_approval needs DRAFT + non-zero total.
  • approve_requisition gates by role threshold ladder:
      ≤ 5,000      → junior
      ≤ 50,000     → senior
      ≤ 500,000    → finance manager / CAO
      > 500,000    → admin only
  • reject_requisition requires a reason.
  • convert_to_po only works on APPROVED PRs.
  • match_three_way detects total mismatches (PO ≠ GRN ≠ Invoice).
  • API endpoints respect org isolation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.authentication.models import Organization, User
from apps.procurement import services as proc
from apps.procurement.models import (
    PurchaseRequisition, ThreeWayMatchResult,
)


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Procurement Test Org")


@pytest.fixture
def admin(db, org):
    return User.objects.create_user(
        email="proc-admin@test.local", full_name="Admin", password="x",
        organization=org, role=User.Role.ADMIN,
    )


@pytest.fixture
def junior(db, org):
    return User.objects.create_user(
        email="proc-jr@test.local", full_name="Junior", password="x",
        organization=org, role=User.Role.JUNIOR_AUDITOR,
    )


@pytest.fixture
def senior(db, org):
    return User.objects.create_user(
        email="proc-sr@test.local", full_name="Senior", password="x",
        organization=org, role=User.Role.SENIOR_AUDITOR,
    )


@pytest.fixture
def finance_manager(db, org):
    return User.objects.create_user(
        email="proc-fm@test.local", full_name="FM", password="x",
        organization=org, role=User.Role.FINANCE_MANAGER,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Creation + total computation
# ─────────────────────────────────────────────────────────────────────────────

def test_create_requisition_computes_total_from_lines(db, org, junior):
    pr = proc.create_requisition(
        organization=org, requested_by=junior, title="Laptops",
        lines=[
            {"description": "MacBook", "quantity": 2, "unit_price": 5000},
            {"description": "Mouse",   "quantity": 2, "unit_price": 100},
        ],
    )
    assert pr.total_amount == Decimal("10200.00")
    assert pr.status == PurchaseRequisition.Status.DRAFT
    assert pr.lines.count() == 2
    assert pr.pr_number.startswith("PR-")


def test_pr_number_increments_per_org(db, org, junior):
    p1 = proc.create_requisition(
        organization=org, requested_by=junior, title="A",
        lines=[{"description": "x", "quantity": 1, "unit_price": 100}],
    )
    p2 = proc.create_requisition(
        organization=org, requested_by=junior, title="B",
        lines=[{"description": "y", "quantity": 1, "unit_price": 200}],
    )
    seq1 = int(p1.pr_number.rsplit("-", 1)[-1])
    seq2 = int(p2.pr_number.rsplit("-", 1)[-1])
    assert seq2 == seq1 + 1


# ─────────────────────────────────────────────────────────────────────────────
# Submit
# ─────────────────────────────────────────────────────────────────────────────

def test_submit_zero_total_raises(db, org, junior):
    pr = proc.create_requisition(
        organization=org, requested_by=junior, title="Empty",
        lines=[],
    )
    with pytest.raises(ValueError, match="no value"):
        proc.submit_for_approval(pr, user=junior)


def test_submit_already_submitted_raises(db, org, junior):
    pr = proc.create_requisition(
        organization=org, requested_by=junior, title="OK",
        lines=[{"description": "x", "quantity": 1, "unit_price": 100}],
    )
    proc.submit_for_approval(pr, user=junior)
    with pytest.raises(ValueError, match="cannot submit"):
        proc.submit_for_approval(pr, user=junior)


# ─────────────────────────────────────────────────────────────────────────────
# Approval ladder
# ─────────────────────────────────────────────────────────────────────────────

def test_required_role_set_thresholds():
    junior_set = proc.required_role_set(Decimal("4000"))
    assert User.Role.JUNIOR_AUDITOR in junior_set
    assert User.Role.ADMIN in junior_set

    senior_set = proc.required_role_set(Decimal("20000"))
    assert User.Role.JUNIOR_AUDITOR not in senior_set
    assert User.Role.SENIOR_AUDITOR in senior_set

    fm_set = proc.required_role_set(Decimal("250000"))
    assert User.Role.SENIOR_AUDITOR not in fm_set
    assert User.Role.FINANCE_MANAGER in fm_set

    admin_set = proc.required_role_set(Decimal("9999999"))
    assert admin_set == {User.Role.ADMIN}


def test_junior_cannot_approve_50k_pr(db, org, junior):
    pr = proc.create_requisition(
        organization=org, requested_by=junior, title="Server",
        lines=[{"description": "rack", "quantity": 1, "unit_price": 30000}],
    )
    proc.submit_for_approval(pr, user=junior)
    with pytest.raises(PermissionError):
        proc.approve_requisition(pr, user=junior)


def test_senior_can_approve_30k_pr(db, org, senior, junior):
    pr = proc.create_requisition(
        organization=org, requested_by=junior, title="Server",
        lines=[{"description": "rack", "quantity": 1, "unit_price": 30000}],
    )
    proc.submit_for_approval(pr, user=junior)
    proc.approve_requisition(pr, user=senior, notes="ok")
    pr.refresh_from_db()
    assert pr.status == PurchaseRequisition.Status.APPROVED
    assert pr.approved_by_id == senior.id
    assert pr.approvals.count() == 1


def test_senior_cannot_approve_600k_pr(db, org, senior, junior):
    pr = proc.create_requisition(
        organization=org, requested_by=junior, title="Big",
        lines=[{"description": "rack", "quantity": 1, "unit_price": 600000}],
    )
    proc.submit_for_approval(pr, user=junior)
    with pytest.raises(PermissionError):
        proc.approve_requisition(pr, user=senior)


def test_admin_can_approve_anything(db, org, admin, junior):
    pr = proc.create_requisition(
        organization=org, requested_by=junior, title="Massive",
        lines=[{"description": "rack", "quantity": 1, "unit_price": 999999}],
    )
    proc.submit_for_approval(pr, user=junior)
    proc.approve_requisition(pr, user=admin, notes="ceo signed off")
    pr.refresh_from_db()
    assert pr.status == PurchaseRequisition.Status.APPROVED


# ─────────────────────────────────────────────────────────────────────────────
# Reject + convert
# ─────────────────────────────────────────────────────────────────────────────

def test_reject_requires_reason(db, org, junior, finance_manager):
    pr = proc.create_requisition(
        organization=org, requested_by=junior, title="X",
        lines=[{"description": "x", "quantity": 1, "unit_price": 100}],
    )
    proc.submit_for_approval(pr, user=junior)
    with pytest.raises(ValueError, match="reason"):
        proc.reject_requisition(pr, user=finance_manager, reason="")


def test_reject_records_audit_trail(db, org, junior, finance_manager):
    pr = proc.create_requisition(
        organization=org, requested_by=junior, title="X",
        lines=[{"description": "x", "quantity": 1, "unit_price": 100}],
    )
    proc.submit_for_approval(pr, user=junior)
    proc.reject_requisition(pr, user=finance_manager, reason="over budget")
    pr.refresh_from_db()
    assert pr.status == PurchaseRequisition.Status.REJECTED
    assert pr.rejection_reason == "over budget"
    assert pr.approvals.filter(decision="rejected").exists()


def test_convert_to_po_requires_approved(db, org, junior):
    pr = proc.create_requisition(
        organization=org, requested_by=junior, title="X",
        lines=[{"description": "x", "quantity": 1, "unit_price": 100}],
    )
    with pytest.raises(ValueError, match="APPROVED"):
        proc.convert_to_po(pr, user=junior)


def test_convert_to_po_creates_po_and_closes_pr(db, org, admin, junior):
    pr = proc.create_requisition(
        organization=org, requested_by=junior, title="Servers",
        vendor_name="Acme",
        lines=[{"description": "rack", "quantity": 1, "unit_price": 1000}],
    )
    proc.submit_for_approval(pr, user=junior)
    proc.approve_requisition(pr, user=admin)
    po = proc.convert_to_po(pr, user=admin)
    pr.refresh_from_db()
    assert pr.status == PurchaseRequisition.Status.CLOSED
    assert pr.purchase_order_id == po.id
    assert po.total_amount == Decimal("1000")


# ─────────────────────────────────────────────────────────────────────────────
# Three-way match
# ─────────────────────────────────────────────────────────────────────────────

def test_match_three_way_pending_when_grn_missing(db, org, admin, junior):
    pr = proc.create_requisition(
        organization=org, requested_by=junior, title="x",
        lines=[{"description": "x", "quantity": 1, "unit_price": 1000}],
    )
    proc.submit_for_approval(pr, user=junior)
    proc.approve_requisition(pr, user=admin)
    po = proc.convert_to_po(pr, user=admin)

    match = proc.match_three_way(po)
    assert match.status == ThreeWayMatchResult.Status.PENDING


def test_match_three_way_total_mismatch(db, org, admin, junior):
    """PO totalled at 1000, but invoice claims 1500 — mismatch."""
    from apps.invoices.models import Invoice
    from apps.documents.typed_models import GoodsReceiptNote

    pr = proc.create_requisition(
        organization=org, requested_by=junior, title="x", vendor_name="Acme",
        lines=[{"description": "x", "quantity": 1, "unit_price": 1000}],
    )
    proc.submit_for_approval(pr, user=junior)
    proc.approve_requisition(pr, user=admin)
    po = proc.convert_to_po(pr, user=admin)

    # `grn_date`, not `receipt_date` — the latter is not a field on this model,
    # and `document` is required by AuditMixin on every typed record.
    from apps.documents.models import Document

    grn_document = Document.objects.create(
        organization=org, uploaded_by=admin, original_filename="grn-1.pdf",
        file="", file_size=0, mime_type="application/pdf",
        document_type=Document.DocumentType.PURCHASE_ORDER,
    )
    grn = GoodsReceiptNote.objects.create(
        organization=org, document=grn_document, grn_number="GRN-1",
        grn_date=date.today(), vendor_name="Acme",
        total_amount=Decimal("1000"),
    )
    inv = Invoice.objects.create(
        organization=org, uploaded_by=admin,
        invoice_number="INV-1", vendor_name="Acme",
        subtotal=Decimal("1500"), total_amount=Decimal("1500"),
        invoice_date=date.today(), currency="SAR",
        original_filename="x.pdf",
    )
    match = proc.match_three_way(po, grn=grn, invoice=inv)
    assert match.status in {
        ThreeWayMatchResult.Status.MISMATCH,
        ThreeWayMatchResult.Status.PARTIAL,
    }
    assert any(d.get("field") == "total_amount" for d in match.differences)


# ─────────────────────────────────────────────────────────────────────────────
# API smoke
# ─────────────────────────────────────────────────────────────────────────────

def test_api_requisition_create_and_list(db, org, junior):
    from rest_framework.test import APIClient
    client = APIClient()
    client.force_authenticate(user=junior)

    resp = client.post(
        "/api/v1/procurement/requisitions/",
        {
            "title": "API PR",
            "lines": [
                {"description": "thing", "quantity": 1, "unit_price": 250},
            ],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert float(resp.data["total_amount"]) == 250.0
    assert resp.data["status"] == "draft"

    resp = client.get("/api/v1/procurement/requisitions/")
    assert resp.status_code == 200
    assert len(resp.data["results"]) == 1


def test_api_org_isolation(db, org, junior):
    """A user from a different org must not see this org's PRs."""
    from rest_framework.test import APIClient
    other_org = Organization.objects.create(name="Other Org")
    other_user = User.objects.create_user(
        email="other@test.local", full_name="Other", password="x",
        organization=other_org, role=User.Role.JUNIOR_AUDITOR,
    )
    proc.create_requisition(
        organization=org, requested_by=junior, title="secret",
        lines=[{"description": "x", "quantity": 1, "unit_price": 100}],
    )

    client = APIClient()
    client.force_authenticate(user=other_user)
    resp = client.get("/api/v1/procurement/requisitions/")
    assert resp.status_code == 200
    assert resp.data["results"] == []
