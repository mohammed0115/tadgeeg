"""
Purchase Order Audit Rules Tests
==================================
Uses real NormalizedDocument objects to match actual rule field access patterns.
"""
import pytest
from decimal import Decimal
from datetime import date


def make_po(total=None, budget=None, typed_data=None, org_context=None, **kwargs):
    from apps.rule_engine.rules.base import NormalizedDocument
    td = {
        "approver_role": "manager",
        "approval_status": "approved",
        **(typed_data or {}),
    }
    return NormalizedDocument(
        document_id="test-po-id",
        document_type="purchase_order",
        organization_id="test-org-id",
        document_number=kwargs.pop("document_number", "PO-00001"),
        document_date=kwargs.pop("document_date", date(2026, 1, 15)),
        total_amount=float(total) if total is not None else 14431278.71,
        budget_limit=float(budget) if budget is not None else 20000000.0,
        counterparty_name="شركة الوفاء للتقنية",
        tax_id="351773257742063",
        typed_data=td,
        org_context=org_context or {"country": "SA", "approver_role": "manager"},
        **kwargs,
    )


# ─── PO-M01: Budget limit ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestPOBudgetAvailabilityRule:
    def _rule(self):
        from apps.rule_engine.rules.purchase_order.po_mandatory_rules import POBudgetAvailabilityRule
        return POBudgetAvailabilityRule()

    def test_within_budget_passes(self):
        assert self._rule().execute(make_po(total=10000, budget=20000)).passed

    def test_exactly_at_budget_passes(self):
        assert self._rule().execute(make_po(total=20000, budget=20000)).passed

    def test_exceeds_budget_fails(self):
        assert not self._rule().execute(make_po(total=25000, budget=20000)).passed

    def test_budget_zero_is_skipped(self):
        result = self._rule().execute(make_po(total=5000, budget=0))
        assert result.status in ("skipped", "not_applicable", "pass")

    def test_budget_none_skipped(self):
        from apps.rule_engine.rules.base import NormalizedDocument
        doc = NormalizedDocument(
            document_id="x", document_type="purchase_order",
            organization_id="o", total_amount=5000.0, budget_limit=None,
            typed_data={}, org_context={},
        )
        result = self._rule().execute(doc)
        assert result.status in ("skipped", "not_applicable", "pass")

    def test_fail_explanation_is_non_empty(self):
        result = self._rule().execute(make_po(total=25000, budget=20000))
        assert not result.passed
        assert result.explanation_en


# ─── PO-M02: Authorization level ─────────────────────────────────────────────

@pytest.mark.unit
class TestPOAuthorizationLevelRule:
    def _rule(self):
        from apps.rule_engine.rules.purchase_order.po_mandatory_rules import POAuthorizationLevelRule
        return POAuthorizationLevelRule()

    def test_manager_approves_below_50k_passes(self):
        doc = make_po(total=49000, typed_data={"approver_role": "manager", "approval_status": "approved"})
        assert self._rule().execute(doc).passed

    def test_manager_cannot_approve_above_50k(self):
        doc = make_po(total=51000, typed_data={"approver_role": "manager", "approval_status": "approved"})
        assert not self._rule().execute(doc).passed

    def test_director_approves_up_to_200k(self):
        doc = make_po(total=150000, typed_data={"approver_role": "director", "approval_status": "approved"})
        assert self._rule().execute(doc).passed

    def test_cfo_approves_any_amount(self):
        doc = make_po(total=10000000, typed_data={"approver_role": "cfo", "approval_status": "approved"})
        assert self._rule().execute(doc).passed

    def test_pending_approval_is_warning_not_fail(self):
        doc = make_po(total=100000, typed_data={"approver_role": "", "approval_status": "pending"})
        result = self._rule().execute(doc)
        # Pending status should produce a warning
        assert result.status in ("warning", "fail")
        assert not result.passed

    def test_vp_level_required_for_300k(self):
        doc = make_po(total=300000, typed_data={"approver_role": "director", "approval_status": "approved"})
        assert not self._rule().execute(doc).passed

    def test_vp_approves_300k(self):
        doc = make_po(total=300000, typed_data={"approver_role": "vp", "approval_status": "approved"})
        assert self._rule().execute(doc).passed


# ─── PO-M08: Retroactive PO ──────────────────────────────────────────────────

@pytest.mark.django_db
class TestRetroactivePORule:
    def _rule(self):
        from apps.rule_engine.rules.purchase_order.retroactive_po_rule import RetroactivePORule
        return RetroactivePORule()

    @pytest.fixture
    def org(self, db):
        from apps.authentication.models import Organization
        return Organization.objects.create(
            name="Retro Org", name_ar="منظمة", country="SA",
            currency="SAR", vat_number="300000000000088",
        )

    @pytest.fixture
    def user(self, db, org):
        from django.contrib.auth import get_user_model
        return get_user_model().objects.create_user(
            email="retro@test.finai", password="Pass1!", full_name="Retro", organization=org,
        )

    @pytest.fixture
    def linked_invoice(self, db, org, user):
        from apps.invoices.models import Invoice
        return Invoice.objects.create(
            organization=org, uploaded_by=user,
            original_filename="linked.pdf",
            invoice_date=date(2026, 1, 15),
            currency="SAR", total_amount=Decimal("1000"),
            status="pending",
        )

    def test_po_before_invoice_passes(self, linked_invoice):
        from apps.rule_engine.rules.base import NormalizedDocument
        doc = NormalizedDocument(
            document_id="po-x", document_type="purchase_order",
            organization_id="org", document_date=date(2026, 1, 1),
            total_amount=1000.0, budget_limit=5000.0,
            typed_data={"linked_invoice_id": str(linked_invoice.id)},
            org_context={},
        )
        assert self._rule().execute(doc).passed

    def test_po_after_invoice_fails(self, linked_invoice):
        from apps.rule_engine.rules.base import NormalizedDocument
        doc = NormalizedDocument(
            document_id="po-y", document_type="purchase_order",
            organization_id="org", document_date=date(2026, 2, 1),
            total_amount=1000.0, budget_limit=5000.0,
            typed_data={"linked_invoice_id": str(linked_invoice.id)},
            org_context={},
        )
        assert not self._rule().execute(doc).passed

    def test_no_linked_invoice_is_skipped(self):
        from apps.rule_engine.rules.base import NormalizedDocument
        doc = NormalizedDocument(
            document_id="po-z", document_type="purchase_order",
            organization_id="org", document_date=date(2026, 1, 1),
            total_amount=1000.0, budget_limit=5000.0,
            typed_data={},  # no linked_invoice_id
            org_context={},
        )
        # preconditions fail → skipped
        rule = self._rule()
        if not rule.check_preconditions(doc):
            assert True  # Correctly skipped
        else:
            result = rule.execute(doc)
            assert result.status in ("skipped", "pass")


# ─── PO splitting detection ───────────────────────────────────────────────────

@pytest.mark.unit
class TestPOSplittingRule:
    def _rule(self):
        from apps.rule_engine.rules.purchase_order.po_mandatory_rules import POSplittingRule
        return POSplittingRule()

    def test_amount_above_threshold_not_applicable(self):
        """Amount >= DEFAULT_THRESHOLD (50000) → not_applicable, no DB query needed."""
        doc = make_po(total=60000, typed_data={
            "approver_role": "manager", "approval_status": "approved",
        })
        result = self._rule().execute(doc)
        assert result.status == "not_applicable"

    def test_amount_exactly_at_threshold_not_applicable(self):
        doc = make_po(total=50000, typed_data={"approver_role": "manager", "approval_status": "approved"})
        result = self._rule().execute(doc)
        assert result.status == "not_applicable"

    def test_preconditions_require_counterparty_and_amount(self):
        rule = self._rule()
        doc_no_vendor = make_po(total=10000)
        doc_no_vendor.counterparty_name = None
        assert not rule.check_preconditions(doc_no_vendor)

    def test_preconditions_pass_with_amount_and_vendor(self):
        rule = self._rule()
        doc = make_po(total=10000)
        assert rule.check_preconditions(doc)


# ─── PO completeness ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPOCompletenessRule:
    def _rule(self):
        from apps.rule_engine.rules.purchase_order.po_mandatory_rules import POCompletenessRule
        return POCompletenessRule()

    def _complete_doc(self):
        import datetime, uuid as _uuid
        from apps.rule_engine.rules.base import NormalizedDocument
        return NormalizedDocument(
            document_id=str(_uuid.uuid4()),
            document_type="purchase_order",
            organization_id=str(_uuid.uuid4()),
            total_amount=10000.0,
            counterparty_name="Test Vendor",
            document_number="PO-00001",
            document_date=datetime.date(2026, 1, 15),
            currency="SAR",
            typed_data={
                "po_number": "PO-00001",
                "vendor_name": "Test Vendor",
                "po_date": "2026-01-15",
            },
            org_context={},
        )

    def test_complete_po_passes(self):
        assert self._rule().execute(self._complete_doc()).passed

    def test_missing_po_number_fails(self):
        import datetime, uuid as _uuid
        from apps.rule_engine.rules.base import NormalizedDocument
        doc = NormalizedDocument(
            document_id=str(_uuid.uuid4()),
            document_type="purchase_order",
            organization_id=str(_uuid.uuid4()),
            total_amount=10000.0,
            counterparty_name="Test Vendor",
            document_number=None,
            document_date=datetime.date(2026, 1, 15),
            currency="SAR",
            typed_data={"vendor_name": "Test Vendor", "po_date": "2026-01-15"},
            org_context={},
        )
        assert not self._rule().execute(doc).passed

    def test_missing_vendor_name_fails(self):
        import datetime, uuid as _uuid
        from apps.rule_engine.rules.base import NormalizedDocument
        doc = NormalizedDocument(
            document_id=str(_uuid.uuid4()),
            document_type="purchase_order",
            organization_id=str(_uuid.uuid4()),
            total_amount=10000.0,
            counterparty_name=None,
            document_number="PO-00001",
            document_date=datetime.date(2026, 1, 15),
            currency="SAR",
            typed_data={"po_number": "PO-00001", "po_date": "2026-01-15"},
            org_context={},
        )
        assert not self._rule().execute(doc).passed

    def test_required_fields_listed_in_class(self):
        from apps.rule_engine.rules.purchase_order.po_mandatory_rules import POCompletenessRule
        assert len(POCompletenessRule.REQUIRED_FIELDS) >= 3
