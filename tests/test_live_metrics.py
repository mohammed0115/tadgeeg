"""Live operational counters — polled, tenant-scoped, and cheap on purpose.

The WebSocket stack this project carries cannot run. Production serves
`gunicorn finai_backend.wsgi:application`; WSGI has no WebSocket. Nothing
publishes to the channel layer and no template opens a socket. So "real-time"
here is a poll over ordinary HTTP, and the tests that matter are about the
three ways a polled endpoint goes wrong: it leaks another tenant's volume, it
serves a stale number under a live label, or it quietly becomes a load test
against the customer's own database.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from apps.analytics.live_metrics import CACHE_SECONDS, get_live_metrics


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def seeded(db, organization, admin_user):
    from apps.audit.models import AuditFinding
    from apps.documents.models import Document
    from apps.invoices.models import Invoice

    def _document(status):
        return Document.objects.create(
            organization=organization, uploaded_by=admin_user,
            original_filename=f"{status}.pdf", file="", file_size=1,
            mime_type="application/pdf", processing_status=status,
        )

    _document("pending")
    _document("pending")
    _document("processing")

    AuditFinding.objects.create(
        organization=organization, rule_code="DUP-001", rule_name="Duplicate",
        message="x", status=AuditFinding.Status.OPEN,
        severity=AuditFinding.Severity.CRITICAL,
    )
    AuditFinding.objects.create(
        organization=organization, rule_code="VAT-001", rule_name="VAT",
        message="y", status=AuditFinding.Status.OPEN,
        severity=AuditFinding.Severity.LOW,
    )
    AuditFinding.objects.create(
        organization=organization, rule_code="VAT-002", rule_name="VAT",
        message="z", status=AuditFinding.Status.RESOLVED,
        severity=AuditFinding.Severity.CRITICAL,
    )

    Invoice.objects.create(
        organization=organization, uploaded_by=admin_user,
        original_filename="i.pdf", invoice_number="I-1", vendor_name="V",
        invoice_date=date(2026, 3, 1), total_amount=Decimal("100"), currency="SAR",
    )
    return organization


# ── The counting ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_the_counters_reflect_what_is_actually_there(seeded):
    metrics = get_live_metrics(seeded, use_cache=False)

    assert metrics.pending_documents == 2
    assert metrics.processing_documents == 1
    assert metrics.open_findings == 2
    assert metrics.invoices_today == 1


@pytest.mark.django_db
def test_critical_counts_only_the_open_ones(seeded):
    """A resolved critical finding is not a thing anyone needs to act on, and
    counting it keeps a red number on the dashboard forever."""
    assert get_live_metrics(seeded, use_cache=False).critical_findings == 1


@pytest.mark.django_db
def test_an_empty_tenant_reports_zeros_rather_than_failing(organization):
    metrics = get_live_metrics(organization, use_cache=False)

    assert metrics.open_findings == 0
    assert metrics.generated_at, "a snapshot with no timestamp cannot be judged stale"


# ── Tenant isolation ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_another_tenants_volume_does_not_appear(seeded, admin_user):
    """Volume is commercial information even when the rows are not exposed —
    how many invoices a competitor processes is worth knowing."""
    from apps.audit.models import AuditFinding
    from apps.authentication.models import Organization

    other = Organization.objects.create(name="Other", name_ar="أخرى")
    for i in range(40):
        AuditFinding.objects.create(
            organization=other, rule_code="DUP-001", rule_name="Duplicate",
            message=f"other-{i}", status=AuditFinding.Status.OPEN,
        )

    assert get_live_metrics(seeded, use_cache=False).open_findings == 2


@pytest.mark.django_db
def test_the_cache_is_keyed_per_tenant(seeded):
    """One shared cache key would serve one tenant's numbers to another —
    a leak that only shows up under concurrent traffic."""
    from apps.authentication.models import Organization

    other = Organization.objects.create(name="Other", name_ar="أخرى")

    mine = get_live_metrics(seeded)
    theirs = get_live_metrics(other)

    assert mine.open_findings == 2
    assert theirs.open_findings == 0


# ── Staleness is declared, not hidden ────────────────────────────────────────

@pytest.mark.django_db
def test_a_cached_snapshot_says_it_is_cached(seeded):
    """A cached value rendered as "live" is a stale number wearing a live
    label. On a queue depth that is the difference between "nothing is stuck"
    and "we stopped looking"."""
    first = get_live_metrics(seeded)
    second = get_live_metrics(seeded)

    assert first.cached is False
    assert second.cached is True
    assert second.generated_at == first.generated_at


@pytest.mark.django_db
def test_the_cache_can_be_bypassed(seeded):
    from apps.audit.models import AuditFinding

    get_live_metrics(seeded)
    AuditFinding.objects.create(
        organization=seeded, rule_code="NEW-1", rule_name="New",
        message="new", status=AuditFinding.Status.OPEN,
    )

    assert get_live_metrics(seeded).open_findings == 2            # cached
    assert get_live_metrics(seeded, use_cache=False).open_findings == 3


@pytest.mark.django_db
def test_the_client_is_told_how_often_to_poll(seeded):
    """Served in the payload rather than hardcoded in JavaScript, so the rate
    can be raised under load without a deploy."""
    assert get_live_metrics(seeded, use_cache=False).poll_after_seconds > 0


# ── Cost ─────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_the_uncached_snapshot_stays_within_a_query_budget(seeded, django_assert_num_queries):
    """This runs on every open tab. One careless join turns a counter into a
    self-inflicted load test against the customer's own database."""
    with django_assert_num_queries(4):
        get_live_metrics(seeded, use_cache=False)


@pytest.mark.django_db
def test_a_cached_snapshot_costs_no_queries_at_all(seeded, django_assert_num_queries):
    get_live_metrics(seeded)

    with django_assert_num_queries(0):
        get_live_metrics(seeded)


# ── HTTP ─────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_the_endpoint_serves_a_subscribed_org(seeded, admin_user):
    from tests.conftest import activate_trial

    activate_trial(admin_user.organization)

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.get("/api/v1/analytics/live/")

    assert response.status_code == 200
    assert response.data["open_findings"] == 2
    assert response.data["generated_at"]


@pytest.mark.django_db
def test_the_endpoint_requires_authentication():
    assert APIClient().get("/api/v1/analytics/live/").status_code in (401, 403)


# ── The transport this deliberately does not use ─────────────────────────────

def test_production_serves_wsgi_so_a_socket_api_would_be_a_broken_promise():
    """Named so the next person to reach for the WebSocket stack checks first.

    `channels`, `channels_redis`, CHANNEL_LAYERS, ASGI_APPLICATION and an
    AlertConsumer on ws/alerts/ are all present and all inert. If this test
    fails because the server moved to ASGI, the socket path becomes real and
    this polling endpoint can be revisited.
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    dockerfile = (repo / "Dockerfile").read_text(encoding="utf-8")
    compose = (repo / "deployment/docker/docker-compose.yml").read_text(encoding="utf-8")

    assert "wsgi:application" in dockerfile
    assert "wsgi:application" in compose
    assert "asgi:application" not in compose, (
        "the server moved to ASGI — the WebSocket consumer can work now, and "
        "apps/analytics/live_metrics.py explains what to reconsider"
    )
