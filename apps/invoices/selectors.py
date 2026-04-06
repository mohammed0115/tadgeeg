"""
Vendor Intelligence — Selector Layer
=====================================

Selectors are read-only query objects.  They own all ORM lookups for
VendorProfile so that views, tasks, and report services never embed raw
QuerySet logic.

Design rules
------------
  • Each public method accepts ``organization`` (or ``organization_id``) as its
    first positional argument — this enforces tenant isolation at the query
    level; callers cannot accidentally query across organisations.
  • Methods return QuerySets, dicts, or typed dataclasses — never ORM model
    instances that might be accidentally mutated.
  • No writes — selectors NEVER call .save(), .update(), .create(), or
    .delete().  Write paths live in VendorIntelligenceService.

Usage
-----
    from apps.invoices.selectors import VendorIntelligenceSelector

    sel  = VendorIntelligenceSelector()
    qs   = sel.list_by_org(request.user.organization, risk_tier="high")
    prof = sel.get_by_pk(request.user.organization, pk=vendor_pk)
    stats = sel.org_stats(request.user.organization)
    top  = sel.top_risky(request.user.organization, limit=10)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from django.db.models import Avg, Count, Q, QuerySet, Sum

from apps.invoices.models import VendorProfile


# ── Typed output ───────────────────────────────────────────────────────────────

@dataclass
class VendorOrgStats:
    """
    Aggregated vendor statistics for a single organisation.

    Consumed by dashboards, reports, and the risk engine context.
    """
    total_vendors:          int     = 0
    high_risk_vendors:      int     = 0   # risk_tier in {high, blocked}
    blocked_vendors:        int     = 0
    unapproved_vendors:     int     = 0
    new_vendors:            int     = 0
    avg_risk_score:         float   = 0.0
    avg_frequency_30d:      float   = 0.0
    total_compliance_issues: int    = 0
    total_invoices:         int     = 0
    total_spend:            Decimal = field(default_factory=lambda: Decimal("0"))

    def to_dict(self) -> dict:
        return {
            "total_vendors":           self.total_vendors,
            "high_risk_vendors":       self.high_risk_vendors,
            "blocked_vendors":         self.blocked_vendors,
            "unapproved_vendors":      self.unapproved_vendors,
            "new_vendors":             self.new_vendors,
            "avg_risk_score":          round(self.avg_risk_score, 2),
            "avg_frequency_30d":       round(self.avg_frequency_30d, 2),
            "total_compliance_issues": self.total_compliance_issues,
            "total_invoices":          self.total_invoices,
            "total_spend":             str(self.total_spend),
        }


# ── Selector ───────────────────────────────────────────────────────────────────

class VendorIntelligenceSelector:
    """
    Stateless, read-only query object for VendorProfile data.

    All methods filter by organisation first, so tenant isolation is
    guaranteed regardless of caller code.
    """

    # ── Core lookups ──────────────────────────────────────────────────────────

    def get_by_pk(
        self,
        organization,
        pk,
    ) -> Optional[VendorProfile]:
        """
        Return the VendorProfile with ``pk`` that belongs to ``organization``.
        Returns None (never raises) when not found or cross-tenant access is
        attempted.
        """
        return (
            VendorProfile.objects
            .filter(organization=organization, pk=pk)
            .first()
        )

    def get_by_name(
        self,
        organization,
        vendor_name: str,
    ) -> Optional[VendorProfile]:
        """Case-insensitive lookup by vendor name within a single tenant."""
        return (
            VendorProfile.objects
            .filter(organization=organization, vendor_name__iexact=vendor_name.strip())
            .first()
        )

    def get_by_vat(
        self,
        organization,
        vat_number: str,
    ) -> Optional[VendorProfile]:
        """Lookup by VAT registration number within a single tenant."""
        return (
            VendorProfile.objects
            .filter(organization=organization, vendor_vat_number=vat_number.strip())
            .first()
        )

    # ── Filtered lists ────────────────────────────────────────────────────────

    def list_by_org(
        self,
        organization,
        *,
        risk_tier:   Optional[str]  = None,
        is_approved: Optional[bool] = None,
        is_new:      Optional[bool] = None,
        is_suspicious: Optional[bool] = None,
        search:      Optional[str]  = None,
        min_risk_score: Optional[float] = None,
        order_by: str = "-risk_score",
    ) -> QuerySet:
        """
        Filtered, tenant-scoped QuerySet of VendorProfile rows.

        Parameters
        ----------
        risk_tier       "low" | "medium" | "high" | "blocked"
        is_approved     True / False / None (all)
        is_new          Filter to first-time vendors
        is_suspicious   Filter to suspicious vendors
        search          Case-insensitive substring match on vendor_name
        min_risk_score  Lower bound on risk_score
        order_by        ORM ordering string (default: -risk_score)

        Returns
        -------
        QuerySet[VendorProfile] — unevaluated; caller can slice or paginate.
        """
        qs = VendorProfile.objects.filter(organization=organization)

        if risk_tier:
            # Caller can pass a comma-separated list: "high,blocked"
            tiers = [t.strip() for t in risk_tier.split(",") if t.strip()]
            qs = qs.filter(risk_tier__in=tiers)

        if is_approved is not None:
            qs = qs.filter(is_approved=is_approved)

        if is_new is not None:
            qs = qs.filter(is_new=is_new)

        if is_suspicious is not None:
            qs = qs.filter(is_suspicious=is_suspicious)

        if search:
            qs = qs.filter(vendor_name__icontains=search.strip())

        if min_risk_score is not None:
            qs = qs.filter(risk_score__gte=min_risk_score)

        return qs.order_by(order_by)

    def high_risk(
        self,
        organization,
        *,
        include_blocked: bool = True,
        limit: int = 100,
    ) -> QuerySet:
        """Shortcut: high-risk and/or blocked vendors, ordered by risk_score desc."""
        tiers = ["high", "blocked"] if include_blocked else ["high"]
        return (
            VendorProfile.objects
            .filter(organization=organization, risk_tier__in=tiers)
            .order_by("-risk_score", "-updated_at")[:limit]
        )

    def blocked(self, organization) -> QuerySet:
        """All vendors on the blocked tier for this tenant."""
        return VendorProfile.objects.filter(
            organization=organization,
            risk_tier=VendorProfile.RiskTier.BLOCKED,
        ).order_by("-risk_score")

    def with_compliance_issues(self, organization, min_issues: int = 1) -> QuerySet:
        """Vendors that have at least ``min_issues`` compliance issues."""
        return (
            VendorProfile.objects
            .filter(organization=organization, compliance_issue_count__gte=min_issues)
            .order_by("-compliance_issue_count", "-risk_score")
        )

    def with_duplicate_invoices(self, organization, min_count: int = 1) -> QuerySet:
        """Vendors with at least ``min_count`` duplicate invoices."""
        return (
            VendorProfile.objects
            .filter(organization=organization, duplicate_count__gte=min_count)
            .order_by("-duplicate_count", "-risk_score")
        )

    def new_vendors(self, organization) -> QuerySet:
        """Vendors seen for the first time (is_new=True)."""
        return (
            VendorProfile.objects
            .filter(organization=organization, is_new=True)
            .order_by("-updated_at")
        )

    # ── Aggregated statistics ─────────────────────────────────────────────────

    def org_stats(self, organization) -> VendorOrgStats:
        """
        Return aggregated intelligence statistics for a single organisation.

        Used by the vendor dashboard summary cards and audit reports.
        A single DB round-trip via aggregate().
        """
        agg = VendorProfile.objects.filter(organization=organization).aggregate(
            total_vendors=Count("id"),
            high_risk_vendors=Count(
                "id", filter=Q(risk_tier__in=["high", "blocked"])
            ),
            blocked_vendors=Count(
                "id", filter=Q(risk_tier=VendorProfile.RiskTier.BLOCKED)
            ),
            unapproved_vendors=Count(
                "id", filter=Q(is_approved=False)
            ),
            new_vendors=Count(
                "id", filter=Q(is_new=True)
            ),
            avg_risk_score=Avg("risk_score"),
            avg_frequency_30d=Avg("transaction_frequency_30d"),
            total_compliance_issues=Sum("compliance_issue_count"),
            total_invoices=Sum("invoice_count"),
            total_spend=Sum("total_amount"),
        )

        return VendorOrgStats(
            total_vendors=          int(agg.get("total_vendors")           or 0),
            high_risk_vendors=      int(agg.get("high_risk_vendors")       or 0),
            blocked_vendors=        int(agg.get("blocked_vendors")         or 0),
            unapproved_vendors=     int(agg.get("unapproved_vendors")      or 0),
            new_vendors=            int(agg.get("new_vendors")             or 0),
            avg_risk_score=         float(agg.get("avg_risk_score")        or 0.0),
            avg_frequency_30d=      float(agg.get("avg_frequency_30d")     or 0.0),
            total_compliance_issues=int(agg.get("total_compliance_issues") or 0),
            total_invoices=         int(agg.get("total_invoices")          or 0),
            total_spend=            Decimal(str(agg.get("total_spend")     or "0")),
        )

    def top_risky(self, organization, limit: int = 10) -> QuerySet:
        """
        Return the top ``limit`` vendors ordered by risk_score descending.

        Used by the executive risk report and dashboard widgets.
        """
        return (
            VendorProfile.objects
            .filter(organization=organization)
            .order_by("-risk_score", "-compliance_issue_count")[:limit]
        )

    def risk_score_distribution(self, organization) -> dict[str, int]:
        """
        Return count of vendors per risk tier for pie/bar charts.

        Returns
        -------
        {"low": N, "medium": N, "high": N, "blocked": N}
        """
        agg = VendorProfile.objects.filter(organization=organization).aggregate(
            low=Count("id",     filter=Q(risk_tier=VendorProfile.RiskTier.LOW)),
            medium=Count("id",  filter=Q(risk_tier=VendorProfile.RiskTier.MEDIUM)),
            high=Count("id",    filter=Q(risk_tier=VendorProfile.RiskTier.HIGH)),
            blocked=Count("id", filter=Q(risk_tier=VendorProfile.RiskTier.BLOCKED)),
        )
        return {
            "low":     int(agg.get("low")     or 0),
            "medium":  int(agg.get("medium")  or 0),
            "high":    int(agg.get("high")    or 0),
            "blocked": int(agg.get("blocked") or 0),
        }

    # ── Transaction / compliance history helpers ───────────────────────────────

    def recent_transactions(
        self,
        organization,
        vendor_name: str,
        limit: int = 20,
    ) -> list[dict]:
        """
        Return the ``limit`` most recent transaction events for a vendor.

        Reads from the embedded JSON in ``transaction_history.recent_documents``
        so there is no additional DB round-trip beyond the profile fetch.
        """
        profile = self.get_by_name(organization, vendor_name)
        if not profile:
            return []
        history = profile.transaction_history or {}
        recent = history.get("recent_documents", []) or []
        return recent[:limit]

    def compliance_summary(
        self,
        organization,
        vendor_name: str,
    ) -> dict:
        """
        Return the compliance_history dict for a single vendor.

        Keys: total_issues, last_failed_rules, last_risk_level,
              last_risk_score, last_anomaly_score, updated_at
        """
        profile = self.get_by_name(organization, vendor_name)
        if not profile:
            return {}
        return profile.compliance_history or {}

    # ── RiskEngine context helper ─────────────────────────────────────────────

    def build_risk_context(
        self,
        organization,
        vendor_name: str,
        tax_id: Optional[str] = None,
    ) -> dict:
        """
        Build the vendor_context dict consumed by the RiskEngine pipeline.

        This is the thin selector equivalent of
        ``VendorIntelligenceService.build_vendor_context()``.
        Prefer the service method for write-heavy paths (it handles profile
        creation); use this method in read-only pipeline stages.
        """
        profile = self.get_by_name(organization, vendor_name)
        if not profile and tax_id:
            profile = self.get_by_vat(organization, tax_id)
        if not profile:
            return {}

        flags = list(profile.tags or [])
        if profile.is_suspicious and "suspicious_vendor" not in flags:
            flags.append("suspicious_vendor")
        if profile.risk_tier == VendorProfile.RiskTier.BLOCKED and "blocked_vendor" not in flags:
            flags.append("blocked_vendor")
        elif profile.risk_tier == VendorProfile.RiskTier.HIGH and "high_risk_vendor" not in flags:
            flags.append("high_risk_vendor")

        return {
            "counterparty_name":        profile.vendor_name,
            "tax_id":                   profile.vendor_vat_number,
            "risk_score":               float(profile.risk_score or 0),
            "vendor_risk_score":        float(profile.risk_score or 0),
            "risk_tier":                profile.risk_tier,
            "is_approved":              profile.is_approved,
            "flags":                    flags,
            "transaction_count":        profile.invoice_count,
            "average_transaction_value": float(profile.avg_invoice_amount or 0),
            "frequency_30d":            float(profile.transaction_frequency_30d or 0),
            "compliance_issue_count":   int(profile.compliance_issue_count or 0),
            "high_risk_audit_count":    int(profile.high_risk_audit_count or 0),
            "last_seen":                profile.last_seen.isoformat() if profile.last_seen else None,
        }
