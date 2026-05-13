"""Internal billing report.

Computes the 10 metrics from Docs/payment/00.md §8 and prints them as
either a formatted table (default) or CSV (``--csv``). Run from a
cron, an ops shell, or pipe to a file for spreadsheet review.

Metrics:
  1. Active organizations (have a usable sub right now)
  2. Trialing subscriptions
  3. Active subscriptions
  4. Expired subscriptions
  5. Total invoices used (across all subs)
  6. Total invoices remaining (across usable subs)
  7. Top 10 organizations by used_invoices
  8. Organizations whose remaining quota ≤ 10
  9. Organizations whose ends_at within next 7 days
 10. Expected revenue from currently-active paid plans
"""
from __future__ import annotations

import csv
import io
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.billing.choices import SubscriptionStatus
from apps.billing.models import OrganizationSubscription


def _now():
    return timezone.now()


class Command(BaseCommand):
    help = "Print the billing/usage summary (10 metrics)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv", action="store_true",
            help="Emit summary as CSV instead of a formatted table.",
        )
        parser.add_argument(
            "--low-remaining-threshold", type=int, default=10,
            help="Quota threshold for the 'near depletion' metric (default 10).",
        )
        parser.add_argument(
            "--expiring-window-days", type=int, default=7,
            help="Window for the 'near expiry' metric (default 7 days).",
        )

    # ─────────────────────────────────────────────────────────────── compute

    def _compute(self, *, low_remaining: int, expiring_window: int) -> dict:
        now = _now()
        usable = OrganizationSubscription.objects.filter(
            status__in=(SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING),
            starts_at__lte=now, ends_at__gte=now,
        )

        # 1–4: status counts.
        counts = OrganizationSubscription.objects.values("status").annotate(n=Count("id"))
        by_status = {row["status"]: row["n"] for row in counts}

        # 5: total invoices used (any subscription, all time).
        total_used = (
            OrganizationSubscription.objects.aggregate(
                s=Coalesce(Sum("used_invoices"), 0),
            )["s"] or 0
        )

        # 6: total remaining quota across *usable* subs only.
        remaining_expr = ExpressionWrapper(
            F("invoice_limit") - F("used_invoices") - F("reserved_invoices"),
            output_field=DecimalField(max_digits=12, decimal_places=0),
        )
        total_remaining = (
            usable.annotate(_rem=remaining_expr)
                  .aggregate(s=Coalesce(Sum("_rem"), Value(0), output_field=DecimalField()))["s"]
            or 0
        )

        # 7: top 10 orgs by used_invoices (lifetime, all subs).
        top10 = list(
            OrganizationSubscription.objects
            .values("organization__name", "organization_id")
            .annotate(used=Sum("used_invoices"))
            .order_by("-used")[:10]
        )

        # 8: orgs nearly out of quota.
        near_depletion = list(
            usable
            .annotate(_rem=remaining_expr)
            .filter(_rem__lte=low_remaining)
            .order_by("_rem")
            .values_list("organization__name", "_rem", "plan__code")[:20]
        )

        # 9: orgs whose subscription ends within the window.
        cutoff = now + timedelta(days=expiring_window)
        near_expiry = list(
            usable
            .filter(ends_at__lte=cutoff)
            .order_by("ends_at")
            .values_list("organization__name", "ends_at", "plan__code")[:50]
        )

        # 10: expected revenue from active (paid) plans.
        expected_revenue = (
            usable
            .filter(plan__is_free=False)
            .aggregate(s=Coalesce(Sum("plan__price"), Value(Decimal("0")),
                                   output_field=DecimalField(max_digits=14, decimal_places=2)))["s"]
        ) or Decimal("0")

        return {
            "as_of":               now.isoformat(timespec="seconds"),
            "orgs_with_usable":    usable.values("organization_id").distinct().count(),
            "trialing_count":      by_status.get(SubscriptionStatus.TRIALING, 0),
            "active_count":        by_status.get(SubscriptionStatus.ACTIVE, 0),
            "expired_count":       by_status.get(SubscriptionStatus.EXPIRED, 0),
            "pending_payment":     by_status.get(SubscriptionStatus.PENDING_PAYMENT, 0),
            "payment_failed":      by_status.get(SubscriptionStatus.PAYMENT_FAILED, 0),
            "canceled":            by_status.get(SubscriptionStatus.CANCELED, 0),
            "total_used":          int(total_used),
            "total_remaining":     int(total_remaining),
            "expected_revenue":    expected_revenue,
            "top10":               top10,
            "near_depletion":      near_depletion,
            "near_expiry":         near_expiry,
        }

    # ──────────────────────────────────────────────────────────── handlers

    def handle(self, *args, **options):
        data = self._compute(
            low_remaining=options["low_remaining_threshold"],
            expiring_window=options["expiring_window_days"],
        )
        if options["csv"]:
            self._emit_csv(data)
        else:
            self._emit_table(data)

    # ────────────────────────────────────────────────────────────── format

    def _emit_table(self, d: dict) -> None:
        w = self.stdout.write
        bar = "─" * 60
        w(self.style.MIGRATE_HEADING(f"Billing Report — as of {d['as_of']}"))
        w(bar)

        rows = [
            ("Organizations with usable sub",  d["orgs_with_usable"]),
            ("Trialing subscriptions",          d["trialing_count"]),
            ("Active subscriptions",            d["active_count"]),
            ("Expired subscriptions",           d["expired_count"]),
            ("Pending-payment subscriptions",   d["pending_payment"]),
            ("Payment-failed subscriptions",    d["payment_failed"]),
            ("Canceled subscriptions",          d["canceled"]),
            ("Total invoices used (lifetime)",  d["total_used"]),
            ("Total invoices remaining (now)",  d["total_remaining"]),
            ("Expected MRR (paid usable plans)", f"{d['expected_revenue']} SAR"),
        ]
        for label, value in rows:
            w(f"  {label:<38} {value}")

        w("")
        w(self.style.MIGRATE_LABEL("Top 10 organizations by usage"))
        w(bar)
        if not d["top10"]:
            w("  (none)")
        for row in d["top10"]:
            w(f"  {row['organization__name'][:40]:<40} used={row['used']}")

        w("")
        w(self.style.MIGRATE_LABEL("Near-depletion (≤ threshold)"))
        w(bar)
        if not d["near_depletion"]:
            w("  (none)")
        for name, remaining, plan in d["near_depletion"]:
            w(f"  {name[:34]:<34} plan={plan:<14} remaining={remaining}")

        w("")
        w(self.style.MIGRATE_LABEL("Near-expiry (within window)"))
        w(bar)
        if not d["near_expiry"]:
            w("  (none)")
        for name, ends_at, plan in d["near_expiry"]:
            w(f"  {name[:34]:<34} plan={plan:<14} ends={ends_at:%Y-%m-%d}")
        w("")

    def _emit_csv(self, d: dict) -> None:
        # Build the CSV in memory and hand it to self.stdout in one shot.
        # Going through csv.writer(self.stdout) would attach an extra
        # newline per row because OutputWrapper has ending="\n", and
        # going through sys.stdout would bypass call_command(stdout=...)
        # in tests.
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["metric", "value"])
        for key in (
            "as_of", "orgs_with_usable", "trialing_count", "active_count",
            "expired_count", "pending_payment", "payment_failed",
            "canceled", "total_used", "total_remaining",
        ):
            writer.writerow([key, d[key]])
        writer.writerow(["expected_revenue_sar", d["expected_revenue"]])
        writer.writerow([])
        writer.writerow(["top10_org", "top10_used"])
        for row in d["top10"]:
            writer.writerow([row["organization__name"], row["used"]])
        writer.writerow([])
        writer.writerow(["near_depletion_org", "remaining", "plan"])
        for name, rem, plan in d["near_depletion"]:
            writer.writerow([name, rem, plan])
        writer.writerow([])
        writer.writerow(["near_expiry_org", "ends_at", "plan"])
        for name, ends_at, plan in d["near_expiry"]:
            writer.writerow([name, ends_at.isoformat() if ends_at else "", plan])
        self.stdout.write(buf.getvalue(), ending="")
