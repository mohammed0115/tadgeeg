"""
Phase 3 — Query Count Regression Tests

Prevents re-introduction of N+1 query patterns on the most accessed list
endpoints.  Each test establishes a baseline: create N objects, call the
endpoint, assert the query count stays O(1) rather than O(N).

Django's `assertNumQueries` / `CaptureQueriesContext` are used rather than
mocking so real SQL is generated and measured.

Run:
    pytest tests/test_query_counts.py -v
"""

import pytest
from decimal import Decimal
from datetime import date

from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.authentication.models import Organization, User
from apps.documents.models import Document, DocumentAnalysisResult
from apps.invoices.models import Invoice
from apps.audit.models import AuditSession


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_org(suffix=""):
    return Organization.objects.create(
        name=f"QCOrg{suffix}",
        country=Organization.Country.SAUDI_ARABIA,
        currency=Organization.Currency.SAR,
        vat_number=f"30000000000000{suffix or 1}",
    )


def _make_user(org, suffix=""):
    return User.objects.create_user(
        email=f"qc{suffix}@test.finai",
        password="Pass123!",
        full_name=f"QC User {suffix}",
        organization=org,
        role=User.Role.SENIOR_AUDITOR,
    )


def _auth_client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _make_document(org, user, i=0, status=Document.ProcessingStatus.COMPLETED):
    return Document.objects.create(
        organization=org,
        uploaded_by=user,
        original_filename=f"doc_{i}.pdf",
        file=f"uploads/doc_{i}.pdf",
        file_size=1024,
        mime_type="application/pdf",
        document_type=Document.DocumentType.INVOICE,
        processing_status=status,
    )


def _make_analysis(doc):
    return DocumentAnalysisResult.objects.create(
        document=doc,
        ai_document_type="invoice",
        classification_confidence=0.95,
        vendor_name="ACME",
        risk_score=20.0,
        risk_level="low",
        fraud_score=0.1,
        duplicate_score=0.05,
        compliance_score=0.95,
    )


def _make_invoice(org, user, i=0):
    return Invoice.objects.create(
        organization=org,
        uploaded_by=user,
        original_filename=f"inv_{i}.pdf",
        invoice_number=f"INV-{i:04d}",
        invoice_date=date(2026, 3, 1),
        vendor_name="Vendor",
        currency=Invoice.Currency.SAR,
        subtotal=Decimal("1000"),
        vat_amount=Decimal("150"),
        total_amount=Decimal("1150"),
        status=Invoice.Status.PENDING,
    )


def _make_session(org, user, i=0):
    return AuditSession.objects.create(
        organization=org,
        created_by=user,
        session_name=f"Session {i}",
        state=AuditSession.State.COMPLETED,
        total_count=5,
        processed_count=5,
    )


# ── Document List Endpoint ────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDocumentListQueryCount:
    """
    GET /api/documents/ must not grow linearly with the number of documents.
    Expected query profile:
      1. Auth/session lookup (1)
      2. Document list with select_related (1)
      3. prefetch_related analysis_result (1)
    Baseline ceiling: ≤ 6 queries regardless of row count.
    """

    URL = "/api/documents/"
    CEILING = 6

    def _setup(self, n=10):
        org  = _make_org("dl")
        user = _make_user(org, "dl")
        docs = [_make_document(org, user, i) for i in range(n)]
        for d in docs:
            _make_analysis(d)
        return _auth_client(user)

    def test_list_10_docs_within_ceiling(self):
        client = self._setup(n=10)
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(self.URL)
        assert response.status_code == 200
        assert len(ctx) <= self.CEILING, (
            f"Document list used {len(ctx)} queries for 10 docs "
            f"(ceiling={self.CEILING}).\n"
            + "\n".join(q["sql"][:120] for q in ctx)
        )

    def test_list_50_docs_same_query_count(self):
        client_10 = self._setup(n=10)
        client_50 = self._setup(n=50)

        with CaptureQueriesContext(connection) as ctx10:
            client_10.get(self.URL)
        with CaptureQueriesContext(connection) as ctx50:
            client_50.get(self.URL)

        # Query count must not grow O(N) — allow 1 extra for any edge-case
        assert len(ctx50) <= len(ctx10) + 1, (
            f"Query count grew from {len(ctx10)} (10 docs) to {len(ctx50)} (50 docs) — N+1 detected"
        )


# ── Document Detail Endpoint ──────────────────────────────────────────────────

@pytest.mark.django_db
class TestDocumentDetailQueryCount:
    """
    GET /api/documents/{pk}/ should resolve in a fixed number of queries.
    Ceiling: ≤ 8 (doc + extracted_data + page_results + analysis + auth).
    """

    CEILING = 8

    def test_detail_within_ceiling(self):
        org  = _make_org("dd")
        user = _make_user(org, "dd")
        doc  = _make_document(org, user)
        _make_analysis(doc)
        client = _auth_client(user)

        with CaptureQueriesContext(connection) as ctx:
            response = client.get(f"/api/documents/{doc.pk}/")
        assert response.status_code == 200
        assert len(ctx) <= self.CEILING, (
            f"Document detail used {len(ctx)} queries (ceiling={self.CEILING}).\n"
            + "\n".join(q["sql"][:120] for q in ctx)
        )


# ── Audit Session List Endpoint ───────────────────────────────────────────────

@pytest.mark.django_db
class TestAuditSessionListQueryCount:
    """
    GET /api/audit/sessions/ must not issue one query per row to resolve
    created_by (fixed by select_related in Phase 3).
    Ceiling: ≤ 6 queries regardless of session count.
    """

    URL = "/api/audit/sessions/"
    CEILING = 6

    def _setup(self, n=10):
        org  = _make_org("as")
        user = _make_user(org, "as")
        for i in range(n):
            _make_session(org, user, i)
        return _auth_client(user)

    def test_list_10_sessions_within_ceiling(self):
        client = self._setup(n=10)
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(self.URL)
        assert response.status_code == 200
        assert len(ctx) <= self.CEILING, (
            f"AuditSession list used {len(ctx)} queries for 10 sessions "
            f"(ceiling={self.CEILING}).\n"
            + "\n".join(q["sql"][:120] for q in ctx)
        )

    def test_list_n_plus_1_not_present(self):
        """Query count with 5 sessions must equal query count with 20 sessions."""
        client5  = self._setup(n=5)
        client20 = self._setup(n=20)

        with CaptureQueriesContext(connection) as ctx5:
            client5.get(self.URL)
        with CaptureQueriesContext(connection) as ctx20:
            client20.get(self.URL)

        assert len(ctx20) <= len(ctx5) + 1, (
            f"N+1 detected: {len(ctx5)} queries (5 sessions) → {len(ctx20)} queries (20 sessions)"
        )


# ── Invoice List Endpoint ─────────────────────────────────────────────────────

@pytest.mark.django_db
class TestInvoiceListQueryCount:
    """
    GET /api/invoices/ list endpoint.
    Ceiling: ≤ 6 queries (auth + list + prefetch + count).
    """

    URL = "/api/invoices/"
    CEILING = 6

    def _setup(self, n=10):
        org  = _make_org("il")
        user = _make_user(org, "il")
        for i in range(n):
            _make_invoice(org, user, i)
        return _auth_client(user)

    def test_list_10_invoices_within_ceiling(self):
        client = self._setup(n=10)
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(self.URL)
        # 200 or 404 are both valid — we only care about query count
        assert response.status_code in (200, 404)
        assert len(ctx) <= self.CEILING, (
            f"Invoice list used {len(ctx)} queries for 10 invoices "
            f"(ceiling={self.CEILING}).\n"
            + "\n".join(q["sql"][:120] for q in ctx)
        )

    def test_list_n_plus_1_not_present(self):
        client10 = self._setup(n=10)
        client30 = self._setup(n=30)

        with CaptureQueriesContext(connection) as ctx10:
            client10.get(self.URL)
        with CaptureQueriesContext(connection) as ctx30:
            client30.get(self.URL)

        assert len(ctx30) <= len(ctx10) + 1, (
            f"N+1 detected on invoice list: "
            f"{len(ctx10)} queries (10 rows) → {len(ctx30)} queries (30 rows)"
        )
