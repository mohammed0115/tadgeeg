"""Cross-tenant benchmarks — this reads other customers' data, so the tests
are almost entirely about the ways it could leak.

Three properties hold the feature up, and each fails silently if it breaks: an
aggregate still computes with two participants, it just stops being anonymous.
Nothing raises. So each one is pinned here, and the k-anonymity floor gets the
most attention because it is the one a well-meaning refactor is most likely to
relax ("nobody's using it, let's lower the threshold so the page has data").
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.analytics.benchmark_service import MIN_COHORT, BenchmarkService


@pytest.fixture
def make_org(db):
    """An organisation with n invoices and f findings, optionally opted in."""
    from apps.analytics.models import BenchmarkParticipation
    from apps.audit.models import AuditFinding
    from apps.authentication.models import Organization, User
    from apps.invoices.models import Invoice

    counter = {"n": 0}

    def _make(*, invoices, findings, opted_in, name=None):
        counter["n"] += 1
        index = counter["n"]
        org = Organization.objects.create(
            name=name or f"Org {index}", name_ar=f"مؤسسة {index}",
        )
        uploader = User.objects.create_user(
            email=f"u{index}@bench.local", password="StrongPass123!", organization=org,
        )
        for i in range(invoices):
            Invoice.objects.create(
                organization=org, uploaded_by=uploader,
                original_filename=f"{index}-{i}.pdf", invoice_number=f"I{index}-{i}",
                vendor_name="V", invoice_date=date(2026, 3, 1),
                total_amount=Decimal("100"), currency="SAR",
            )
        for i in range(findings):
            AuditFinding.objects.create(
                organization=org, rule_code="DUP-001",
                rule_name="Duplicate", message=f"f{index}-{i}",
            )
        BenchmarkParticipation.objects.create(organization=org, opted_in=opted_in)
        return org

    return _make


# ── Opt-in ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_an_organisation_that_never_opted_in_gets_nothing(make_org):
    """Not an error — a refusal that says why, and contributes nothing."""
    for _ in range(MIN_COHORT + 2):
        make_org(invoices=100, findings=5, opted_in=True)
    mine = make_org(invoices=100, findings=5, opted_in=False)

    result = BenchmarkService(mine).findings_per_hundred_invoices()

    assert result.available is False
    assert "not opted in" in result.reason
    assert result.cohort_median is None


@pytest.mark.django_db
def test_participation_defaults_to_false(db):
    """The default IS the feature. A permissive default would enrol every
    customer in sharing their data by omission."""
    from apps.analytics.models import BenchmarkParticipation
    from apps.authentication.models import Organization

    org = Organization.objects.create(name="Fresh", name_ar="جديدة")
    participation = BenchmarkParticipation.objects.create(organization=org)

    assert participation.opted_in is False


@pytest.mark.django_db
def test_an_organisation_that_did_not_opt_in_is_absent_from_the_cohort(make_org):
    """Not contributing must mean not counted — not merely not shown."""
    for _ in range(MIN_COHORT):
        make_org(invoices=100, findings=2, opted_in=True)
    make_org(invoices=100, findings=900, opted_in=False)   # would skew wildly

    mine = make_org(invoices=100, findings=2, opted_in=True)
    result = BenchmarkService(mine).findings_per_hundred_invoices()

    assert result.cohort_size == MIN_COHORT + 1
    assert result.cohort_median == 2.0, "a non-participant's data entered the aggregate"


# ── k-anonymity ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_a_cohort_below_the_floor_is_refused(make_org):
    """With two participants, either can subtract itself from the average and
    read the other exactly. The aggregate IS the disclosure."""
    for _ in range(MIN_COHORT - 2):
        make_org(invoices=100, findings=5, opted_in=True)
    mine = make_org(invoices=100, findings=5, opted_in=True)

    result = BenchmarkService(mine).findings_per_hundred_invoices()

    assert result.available is False
    assert str(MIN_COHORT) in result.reason
    assert result.cohort_median is None
    assert result.your_value is None


@pytest.mark.django_db
def test_the_refusal_does_not_disclose_how_far_below_the_floor_it_is(make_org):
    """"3 of 5 organisations" is itself a fact about the platform's customers."""
    make_org(invoices=100, findings=5, opted_in=True)
    mine = make_org(invoices=100, findings=5, opted_in=True)

    result = BenchmarkService(mine).findings_per_hundred_invoices()

    assert result.cohort_size == 0
    assert "2" not in result.reason.replace(str(MIN_COHORT), "")


@pytest.mark.django_db
def test_exactly_the_floor_is_enough(make_org):
    """The boundary itself, so an off-by-one in either direction is caught."""
    for _ in range(MIN_COHORT - 1):
        make_org(invoices=100, findings=4, opted_in=True)
    mine = make_org(invoices=100, findings=4, opted_in=True)

    result = BenchmarkService(mine).findings_per_hundred_invoices()

    assert result.available is True
    assert result.cohort_size == MIN_COHORT


# ── What is returned ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_no_other_organisation_is_identifiable_in_the_result(make_org):
    """The result carries a median and a position, never a peer's row."""
    for i in range(MIN_COHORT):
        make_org(invoices=100, findings=i + 1, opted_in=True, name=f"Peer {i}")
    mine = make_org(invoices=100, findings=3, opted_in=True, name="Mine")

    result = BenchmarkService(mine).findings_per_hundred_invoices()
    rendered = str(result.__dict__)

    assert "Peer" not in rendered
    for field in ("organization", "org_id", "peers", "rows"):
        assert field not in result.__dict__


@pytest.mark.django_db
def test_the_metric_is_a_ratio_not_a_total(make_org):
    """Absolute counts leak size, and size plus a sector often identifies a
    company in a market this small."""
    for _ in range(MIN_COHORT):
        make_org(invoices=1000, findings=20, opted_in=True)
    mine = make_org(invoices=50, findings=1, opted_in=True)

    result = BenchmarkService(mine).findings_per_hundred_invoices()

    assert result.your_value == 2.0            # 1 per 50 → 2 per 100
    assert result.cohort_median == 2.0         # 20 per 1000 → 2 per 100
    assert result.available is True


@pytest.mark.django_db
def test_standing_is_words_not_a_bare_number(make_org):
    for _ in range(MIN_COHORT):
        make_org(invoices=100, findings=10, opted_in=True)
    mine = make_org(invoices=100, findings=1, opted_in=True)

    result = BenchmarkService(mine).findings_per_hundred_invoices()

    assert result.standing == "better"
    assert result.percentile is not None


@pytest.mark.django_db
def test_a_tenant_with_no_invoices_is_told_so_rather_than_shown_a_zero(make_org):
    """0 findings per 100 invoices with no invoices is division by nothing, and
    rendering it as "best in cohort" would be a lie in the flattering direction."""
    for _ in range(MIN_COHORT):
        make_org(invoices=100, findings=5, opted_in=True)
    mine = make_org(invoices=0, findings=0, opted_in=True)

    result = BenchmarkService(mine).findings_per_hundred_invoices()

    assert result.available is False
    assert "no audited invoices" in result.reason.lower()


@pytest.mark.django_db
def test_standing_is_unknown_when_the_benchmark_is_unavailable(make_org):
    mine = make_org(invoices=100, findings=5, opted_in=False)
    assert BenchmarkService(mine).findings_per_hundred_invoices().standing == "unknown"
