"""TADGEEG-FIN-AUDIT-9D — Substantive Testing tests (service + recompute + API)."""
from __future__ import annotations

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import substantive_testing as st
from apps.audit.substantive_test_models import SubstantiveTestItem
from apps.authentication.models import Organization, User

_I = SubstantiveTestItem
_Area = _I.Area
_St = _I.Status


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _auditor(org, email="auditor@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Aud Itor",
        role=User.Role.SENIOR_AUDITOR, organization=org)


def _junior(org, email="junior@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Jun Ior",
        role=User.Role.JUNIOR_AUDITOR, organization=org)


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31")


class Base(TestCase):
    def setUp(self):
        self.org = _org(); self.auditor = _auditor(self.org); self.eng = _eng(self.org)


# ── Deterministic recompute helpers ──────────────────────────────────────────
class RecomputeTests(TestCase):
    def test_straight_line_nbv(self):
        r = st.straight_line_nbv(cost=10000, salvage=1000, useful_life_years=5, elapsed_years=2)
        self.assertEqual(r["annual_depreciation"], Decimal("1800.0000"))
        self.assertEqual(r["accumulated_depreciation"], Decimal("3600.0000"))
        self.assertEqual(r["net_book_value"], Decimal("6400.0000"))

    def test_straight_line_caps_at_depreciable(self):
        r = st.straight_line_nbv(cost=10000, salvage=1000, useful_life_years=5, elapsed_years=99)
        # Accumulated never exceeds cost − salvage; NBV floors at salvage.
        self.assertEqual(r["accumulated_depreciation"], Decimal("9000.0000"))
        self.assertEqual(r["net_book_value"], Decimal("1000.0000"))

    def test_zero_life_rejected(self):
        with self.assertRaises(st.SubstantiveTestError):
            st.straight_line_nbv(cost=1, salvage=0, useful_life_years=0, elapsed_years=1)

    def test_net_pay(self):
        self.assertEqual(st.net_pay(gross=8000, deductions=1200), Decimal("6800.0000"))

    def test_inventory_value(self):
        self.assertEqual(st.inventory_value(quantity=30, unit_cost="12.5"), Decimal("375.0000"))


# ── Service workflow ─────────────────────────────────────────────────────────
class ServiceTests(Base):
    def test_create_numbering_and_scoping(self):
        a = st.create_item(engagement=self.eng, actor=self.auditor,
                           area=_Area.INVENTORY, book_value="100")
        b = st.create_item(engagement=self.eng, actor=self.auditor,
                           area=_Area.INVENTORY, book_value="200")
        self.assertEqual(a.reference, "SUB-00001")
        self.assertEqual(b.reference, "SUB-00002")
        self.assertEqual(a.organization_id, self.org.id)
        self.assertEqual(a.status, _St.OPEN)

    def test_inventory_recompute_on_create(self):
        it = st.create_item(engagement=self.eng, actor=self.auditor, area=_Area.INVENTORY,
                            book_value="400",
                            inputs={"quantity": "30", "unit_cost": "12.5"})
        self.assertEqual(it.tested_value, Decimal("375.0000"))
        self.assertEqual(it.variance, Decimal("25.0000"))
        # Outside default zero tolerance → variance.
        self.assertEqual(it.status, _St.VARIANCE)

    def test_fixed_asset_recompute_on_create(self):
        it = st.create_item(engagement=self.eng, actor=self.auditor, area=_Area.FIXED_ASSETS,
                            book_value="6400",
                            inputs={"cost": "10000", "salvage": "1000",
                                    "useful_life_years": "5", "elapsed_years": "2"})
        self.assertEqual(it.tested_value, Decimal("6400.0000"))
        self.assertEqual(it.status, _St.MATCHED)  # book == recomputed NBV

    def test_payroll_recompute_on_create(self):
        it = st.create_item(engagement=self.eng, actor=self.auditor, area=_Area.PAYROLL,
                            book_value="6800",
                            inputs={"gross": "8000", "deductions": "1200"})
        self.assertEqual(it.tested_value, Decimal("6800.0000"))
        self.assertEqual(it.status, _St.MATCHED)

    def test_record_tested_classifies_by_tolerance(self):
        it = st.create_item(engagement=self.eng, actor=self.auditor, area=_Area.INVENTORY,
                            book_value="100", tolerance="5")
        self.assertEqual(it.status, _St.OPEN)
        st.record_tested(item=it, actor=self.auditor, tested_value="103")
        self.assertEqual(it.status, _St.MATCHED)  # |100-103|=3 <= 5
        st.record_tested(item=it, actor=self.auditor, tested_value="120")
        self.assertEqual(it.status, _St.VARIANCE)  # |100-120|=20 > 5

    def test_cancel_blocks_further_testing(self):
        it = st.create_item(engagement=self.eng, actor=self.auditor,
                            area=_Area.OTHER, book_value="10")
        st.cancel(item=it, actor=self.auditor)
        self.assertEqual(it.status, _St.CANCELLED)
        with self.assertRaises(st.SubstantiveTestError):
            st.record_tested(item=it, actor=self.auditor, tested_value="10")

    def test_area_summary(self):
        st.create_item(engagement=self.eng, actor=self.auditor, area=_Area.INVENTORY,
                       book_value="400", inputs={"quantity": "30", "unit_cost": "12.5"})
        st.create_item(engagement=self.eng, actor=self.auditor, area=_Area.PAYROLL,
                       book_value="6800", inputs={"gross": "8000", "deductions": "1200"})
        s = st.area_summary(organization=self.org, engagement=self.eng)
        self.assertEqual(s["inventory"]["total"], 1)
        self.assertEqual(s["inventory"]["variance"], 1)
        self.assertEqual(s["payroll"]["matched"], 1)
        self.assertEqual(s["_totals"]["total"], 2)
        self.assertEqual(s["_totals"]["variance"], 1)


# ── API ──────────────────────────────────────────────────────────────────────
class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.api = APIClient(); self.api.force_authenticate(self.auditor)

    def test_create_list_detail(self):
        resp = self.api.post("/api/v1/audit/substantive-items/", {
            "engagement": str(self.eng.id), "area": "inventory",
            "book_value": "400", "item_reference": "SKU-1",
            "inputs": {"quantity": "30", "unit_cost": "12.5"}}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(Decimal(body["tested_value"]), Decimal("375"))
        self.assertEqual(body["status"], "variance")
        iid = body["id"]
        self.assertTrue(self.api.get(
            f"/api/v1/audit/substantive-items/?engagement={self.eng.id}&area=inventory").json())
        self.assertEqual(self.api.get(f"/api/v1/audit/substantive-items/{iid}/").status_code, 200)

    def test_record_tested_via_api(self):
        it = st.create_item(engagement=self.eng, actor=self.auditor,
                            area=_Area.INVENTORY, book_value="100", tolerance="5")
        resp = self.api.post(f"/api/v1/audit/substantive-items/{it.id}/",
                             {"action": "record", "tested_value": "103"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        it.refresh_from_db()
        self.assertEqual(it.status, _St.MATCHED)

    def test_summary_endpoint(self):
        st.create_item(engagement=self.eng, actor=self.auditor, area=_Area.PAYROLL,
                       book_value="6800", inputs={"gross": "8000", "deductions": "1200"})
        resp = self.api.get(f"/api/v1/audit/engagements/{self.eng.id}/substantive-summary/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["payroll"]["matched"], 1)

    def test_junior_denied(self):
        api = APIClient(); api.force_authenticate(_junior(self.org))
        self.assertEqual(api.get("/api/v1/audit/substantive-items/").status_code, 403)

    def test_cross_org_404(self):
        other = _eng(_org("OrgB"), code="B-1")
        oa = _auditor(other.organization, "o@e.com")
        foreign = st.create_item(engagement=other, actor=oa, area=_Area.OTHER, book_value="1")
        self.assertEqual(self.api.get(
            f"/api/v1/audit/substantive-items/{foreign.id}/").status_code, 404)
        self.assertEqual(self.api.get(
            f"/api/v1/audit/engagements/{other.id}/substantive-summary/").status_code, 404)


# ── Ledger isolation ─────────────────────────────────────────────────────────
class LedgerIsolationTests(Base):
    def test_never_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        it = st.create_item(engagement=self.eng, actor=self.auditor, area=_Area.FIXED_ASSETS,
                            book_value="6400",
                            inputs={"cost": "10000", "salvage": "1000",
                                    "useful_life_years": "5", "elapsed_years": "2"})
        st.record_tested(item=it, actor=self.auditor, tested_value="5000")
        st.area_summary(organization=self.org, engagement=self.eng)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
