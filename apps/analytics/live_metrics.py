"""Live operational counters — cheap enough to poll, honest about staleness.

**Why polling and not the WebSocket stack that already exists.** The project
carries `channels`, `channels_redis`, a Redis CHANNEL_LAYERS config, an
ASGI_APPLICATION and an AlertConsumer on `ws/alerts/`. None of it can run:
production serves `gunicorn finai_backend.wsgi:application`, and WSGI has no
WebSocket. Nothing publishes to the channel layer either — `group_send` appears
nowhere outside the consumer — and no template opens a socket. The transport is
inert in three independent ways.

Building "real-time analytics" on top of that would be building on nothing.
Switching to ASGI is a deployment change — a different server process, a
different worker model, new failure modes — on a system that has had a rough
day. Worth doing deliberately; not worth doing as a side effect of adding a
counter.

So this serves the same numbers over ordinary HTTP. A dashboard polling every
few seconds is indistinguishable from a socket at the timescales an audit
backlog changes on, and it works on the server that is already running.

**Cheapness is a correctness property here.** A polled endpoint runs on every
open tab; one careless join and it becomes a self-inflicted load test. Every
query below is a COUNT over an indexed column, the result is cached for
`CACHE_SECONDS`, and `test_live_metrics.py` pins the query count so a future
edit cannot quietly add a table scan to something that runs every five seconds.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger("analytics.live")

#: Long enough that a dashboard full of tabs cannot hurt the database, short
#: enough that a number nobody has seen move in a minute looks broken.
CACHE_SECONDS = 5

#: What the client should wait between polls. Served in the payload rather than
#: hardcoded in JavaScript, so it can be raised under load without a deploy.
POLL_INTERVAL_SECONDS = 10


@dataclass
class LiveMetrics:
    """A snapshot, with the time it was taken.

    `generated_at` is not decoration. A cached value rendered as "live" is a
    stale number wearing a live label, and on a queue depth that is the
    difference between "nothing is stuck" and "we stopped looking".
    """

    pending_documents: int = 0
    processing_documents: int = 0
    failed_documents_24h: int = 0
    open_findings: int = 0
    critical_findings: int = 0
    audits_running: int = 0
    invoices_today: int = 0
    generated_at: str = ""
    cached: bool = False
    poll_after_seconds: int = POLL_INTERVAL_SECONDS

    def as_dict(self):
        return asdict(self)


def _cache_key(organization):
    return f"live_metrics:{organization.pk}"


def get_live_metrics(organization, *, use_cache: bool = True) -> LiveMetrics:
    """Current operational counters for one tenant.

    Seven COUNTs, each on an indexed column, collapsed into three round trips
    by grouping per model. Tenant-scoped at every step: a live counter is an
    easy place to leak another organisation's volume, and volume is commercial
    information even when the rows themselves are not exposed.
    """
    key = _cache_key(organization)

    if use_cache:
        cached = cache.get(key)
        if cached is not None:
            cached["cached"] = True
            return LiveMetrics(**cached)

    from django.db.models import Count, Q

    from apps.audit.models import AuditFinding, AuditSession
    from apps.documents.models import Document
    from apps.invoices.models import Invoice

    now = timezone.now()
    day_ago = now - timezone.timedelta(hours=24)
    today = now.date()

    documents = Document.objects.filter(organization=organization).aggregate(
        pending=Count("id", filter=Q(processing_status="pending")),
        processing=Count("id", filter=Q(processing_status="processing")),
        failed=Count("id", filter=Q(processing_status="failed", updated_at__gte=day_ago)),
    )

    findings = AuditFinding.objects.filter(organization=organization).aggregate(
        open=Count("id", filter=Q(status=AuditFinding.Status.OPEN)),
        critical=Count("id", filter=Q(status=AuditFinding.Status.OPEN,
                                      severity=AuditFinding.Severity.CRITICAL)),
    )

    running = AuditSession.objects.filter(
        organization=organization,
        status__in=[AuditSession.Status.EXTRACTING, AuditSession.Status.NORMALIZING,
                    AuditSession.Status.VALIDATING],
    ).count()

    invoices_today = Invoice.objects.filter(
        organization=organization, created_at__date=today,
    ).count()

    metrics = LiveMetrics(
        pending_documents=documents["pending"],
        processing_documents=documents["processing"],
        failed_documents_24h=documents["failed"],
        open_findings=findings["open"],
        critical_findings=findings["critical"],
        audits_running=running,
        invoices_today=invoices_today,
        generated_at=now.isoformat(),
        cached=False,
    )

    if use_cache:
        cache.set(key, metrics.as_dict(), CACHE_SECONDS)

    return metrics
