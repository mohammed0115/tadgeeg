"""Load test for the paths that decide whether Tadgeeg stays up.

    pip install locust
    locust -f deployment/loadtest/audit_pipeline.py --host https://dev.tadgeeg.com

**Why this shape.** The platform assessment recorded performance as "تعذّر
التحقق" — not measured. It still is, and that is the honest state: a
concurrency number nobody has produced is not a capacity claim, and the query
budgets in this codebase (six round trips for the dashboard, four for live
metrics, thirty seconds of statement timeout) are ceilings that have never met
real traffic.

The tasks below are weighted by what actually runs on a busy morning, not by
what is interesting to test:

  · the dashboard, opened by everyone at the start of the day
  · the live-metrics poll, which fires on every open tab every ten seconds and
    is therefore the highest-frequency endpoint in the product by a wide margin
  · the invoice list, the working surface
  · a report render, the expensive one

**Run it against dev.** Not against live: this drives real writes through the
audit pipeline, it consumes the tenant's invoice quota, and a load test that
trips the quota gate stops measuring throughput and starts measuring the 402
path. Point it at a tenant created for the purpose.

**What to watch, in order:**
  1. p95 on /api/v1/analytics/live/ — it runs constantly and is cached; if it
     degrades, the cache is not working and every tab is hitting MySQL
  2. any 402 — the run has exhausted the tenant's quota and the numbers after
     that point are meaningless
  3. any 500 — with three gunicorn workers and a 30s statement timeout, the
     first thing to fail under load is a report render blocking a worker
  4. MySQL `max_execution_time` aborts (error 3024) in the server log — those
     are the guard working, not the guard failing
"""

from __future__ import annotations

import os
import random

try:
    from locust import HttpUser, between, events, task
except ImportError:  # pragma: no cover - locust is not a runtime dependency
    raise SystemExit(
        "locust is not installed. This is a load-test harness, deliberately "
        "kept out of requirements.txt so it is not shipped in the image:\n"
        "    pip install locust"
    )

#: Credentials come from the environment. A load test that carries a password
#: in a file committed to git is a credential leak wearing a test's clothes.
EMAIL = os.environ.get("LOADTEST_EMAIL", "")
PASSWORD = os.environ.get("LOADTEST_PASSWORD", "")


@events.test_start.add_listener
def _refuse_to_run_blind(environment, **kwargs):
    if not EMAIL or not PASSWORD:
        raise SystemExit(
            "Set LOADTEST_EMAIL and LOADTEST_PASSWORD. Use an account in a "
            "tenant created for load testing — this drives real writes and "
            "consumes the tenant's invoice quota."
        )
    host = (environment.host or "").lower()
    if "dev." not in host and "test." not in host and "localhost" not in host:
        raise SystemExit(
            f"Refusing to load-test {environment.host}. Point --host at dev or "
            f"test. Driving this at live consumes a paying tenant's quota and "
            f"competes with real auditors for the same three gunicorn workers."
        )


class Auditor(HttpUser):
    """One logged-in auditor working through a normal morning."""

    # A real user reads between clicks. Zero wait measures how fast the server
    # can refuse connections, which is not a number anyone needs.
    wait_time = between(2, 8)

    def on_start(self):
        page = self.client.get("/login/", name="GET /login/")
        token = page.cookies.get("csrftoken", "")
        response = self.client.post(
            "/login/",
            {"email": EMAIL, "password": PASSWORD},
            headers={"X-CSRFToken": token, "X-Requested-With": "XMLHttpRequest"},
            name="POST /login/",
        )
        if response.status_code >= 400:
            raise SystemExit(f"login failed ({response.status_code}) — check the credentials")

    # ── Weighted by real frequency ───────────────────────────────────────

    @task(30)
    def live_metrics(self):
        """The highest-frequency call in the product: every tab, every 10s.

        Cached for five seconds server-side, so under load most of these must
        cost zero queries. If p95 climbs with concurrency, the cache is not
        doing its job and every tab is reaching the database.
        """
        with self.client.get(
            "/api/v1/analytics/live/", name="GET /analytics/live/", catch_response=True
        ) as response:
            if response.status_code == 402:
                response.failure("402 — the tenant's quota is exhausted; results are now meaningless")
            elif response.elapsed.total_seconds() > 1.0:
                response.failure(f"slow for a cached counter: {response.elapsed.total_seconds():.2f}s")

    @task(10)
    def dashboard(self):
        """Documented contract: six DB round trips, 60-second cache."""
        self.client.get("/dashboard/", name="GET /dashboard/")

    @task(8)
    def invoice_list(self):
        page = random.randint(1, 3)
        self.client.get(f"/invoices/?page={page}", name="GET /invoices/")

    @task(4)
    def vendors(self):
        """Carries the risk/frequency/compliance columns added in this branch —
        one VendorProfile query plus the aggregation, capped at 200 rows."""
        self.client.get("/vendors/", name="GET /vendors/")

    @task(3)
    def reports_index(self):
        self.client.get("/reports/", name="GET /reports/")

    @task(1)
    def render_report_pdf(self):
        """The expensive one. A 30-60 page render can take 5-15s and blocks a
        gunicorn worker for the duration; with three workers, three concurrent
        renders are the whole site.
        """
        listing = self.client.get("/api/v1/reports/", name="GET /api/v1/reports/")
        if listing.status_code != 200:
            return
        try:
            reports = listing.json()
            report_id = (reports.get("results") or reports)[0]["id"]
        except (ValueError, KeyError, IndexError, TypeError):
            return

        with self.client.get(
            f"/api/v1/reports/{report_id}/pdf/",
            name="GET /reports/<id>/pdf/",
            catch_response=True,
        ) as response:
            if response.headers.get("X-Report-PDF-Fallback") == "html":
                response.failure("PDF renderer unavailable — served the HTML fallback")


class Poller(HttpUser):
    """A dashboard left open in a background tab.

    Separated from Auditor because it behaves nothing like a person: it never
    navigates, never thinks, and in a real office there are more of these than
    there are auditors actively clicking. Modelling them as one user type
    understates the polling load, which is the load that never stops.
    """

    wait_time = between(9, 11)

    def on_start(self):
        Auditor.on_start(self)

    @task
    def poll(self):
        self.client.get("/api/v1/analytics/live/", name="GET /analytics/live/ [idle tab]")
