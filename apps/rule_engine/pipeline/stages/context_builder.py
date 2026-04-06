"""
ContextBuilderStage — Stage 2 of AuditPipeline V2.

Enriches NormalizedDocument.org_context with three types of external data:

  vendor_context   Counterparty profile: risk score, approval status, flags.
  history_context  Recent AuditRun history for this vendor/document-type.
  erp_context      ERP-linked data: budget limit, cost-centre, account code.

Each sub-loader is isolated; individual failures degrade gracefully.
All enriched data is injected into normalized_doc.org_context so that
downstream rule classes can access it via doc.get_org("vendor"), etc.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.rule_engine.pipeline.stages.base import BaseStage

if TYPE_CHECKING:
    from apps.rule_engine.pipeline.v2.context import PipelineContext

logger = logging.getLogger("rule_engine.pipeline")

__all__ = ["ContextBuilderStage"]


# ── Sub-loaders ────────────────────────────────────────────────────────────────

class VendorContextLoader:
    """
    Loads the counterparty/vendor profile for this document.

    Currently returns a skeleton populated from NormalizedDocument fields.
    Wire to apps.vendors.models.Vendor (or equivalent) when the vendor
    master is available.
    """

    @staticmethod
    def load(context: "PipelineContext") -> dict:
        doc = context.normalized_doc
        if not doc or not doc.counterparty_name:
            return {}
        try:
            # TODO: Replace stub with real Vendor model query:
            #
            #   from apps.vendors.models import Vendor
            #   vendor = Vendor.objects.filter(
            #       organization_id=doc.organization_id,
            #       name__iexact=doc.counterparty_name,
            #   ).select_related("risk_profile").first()
            #   if vendor:
            #       return {
            #           "id": str(vendor.id),
            #           "risk_score": float(vendor.risk_profile.score or 0),
            #           "is_approved": vendor.is_approved,
            #           "payment_terms": vendor.payment_terms,
            #           "flags": list(vendor.flags.values_list("code", flat=True)),
            #       }
            from apps.invoices.services.vendor_intelligence import VendorIntelligenceService

            vendor_context = VendorIntelligenceService().build_vendor_context(
                organization_id=doc.organization_id,
                vendor_name=doc.counterparty_name,
                tax_id=doc.tax_id,
            )
            if vendor_context:
                return vendor_context

            return {
                "counterparty_name": doc.counterparty_name,
                "tax_id": doc.tax_id,
                "is_approved": None,   # unknown — vendor master not yet wired
                "risk_score": None,
                "flags": [],
            }
        except Exception as exc:
            logger.warning("[context_builder] VendorContextLoader failed: %s", exc)
            return {}


class DocumentHistoryLoader:
    """
    Loads recent completed AuditRun history for the same org/document-type.

    Provides signals like unusual submission frequency and prior high-risk
    results that are useful for risk modifiers and AI heuristics.
    """

    LOOKBACK_DAYS = 90

    @staticmethod
    def load(context: "PipelineContext") -> dict:
        doc = context.normalized_doc
        if not doc:
            return {}
        try:
            from datetime import timedelta
            from django.utils import timezone
            from apps.rule_engine.models import AuditRun

            cutoff = timezone.now() - timedelta(days=DocumentHistoryLoader.LOOKBACK_DAYS)
            qs = AuditRun.objects.filter(
                organization_id=doc.organization_id,
                document_type=doc.document_type,
                status=AuditRun.Status.COMPLETED,
                started_at__gte=cutoff,
            ).exclude(document_id=doc.document_id)

            return {
                "recent_run_count": qs.count(),
                "high_risk_count": qs.filter(risk_level__in=["high", "critical"]).count(),
                "lookback_days": DocumentHistoryLoader.LOOKBACK_DAYS,
            }
        except Exception as exc:
            logger.warning("[context_builder] DocumentHistoryLoader failed: %s", exc)
            return {}


class ERPContextLoader:
    """
    Loads ERP-linked data: budget lines, cost-centre limits, account metadata.

    Returns a minimal dict from NormalizedDocument until an ERP integration
    layer is available.
    """

    @staticmethod
    def load(context: "PipelineContext") -> dict:
        doc = context.normalized_doc
        if not doc:
            return {}
        try:
            # TODO: Wire to ERP integration when available:
            #
            #   from apps.erp.models import BudgetLine
            #   budget = BudgetLine.objects.filter(
            #       organization_id=doc.organization_id,
            #       cost_centre_code=doc.cost_center,
            #       account_code=doc.account_code,
            #       fiscal_year=current_fiscal_year,
            #   ).first()
            return {
                "cost_center": doc.cost_center,
                "account_code": doc.account_code,
                "budget_limit": doc.budget_limit,
                "erp_connected": False,   # flip to True when ERP is live
            }
        except Exception as exc:
            logger.warning("[context_builder] ERPContextLoader failed: %s", exc)
            return {}


# ── Stage ──────────────────────────────────────────────────────────────────────

class ContextBuilderStage(BaseStage):
    """
    Orchestrates the three sub-loaders and injects results into
    normalized_doc.org_context.

    Populates: context.vendor_context, context.history_context,
               context.erp_context, and normalized_doc.org_context["vendor/history/erp"]
    """

    name = "context_builder"

    def _run(self, context: "PipelineContext") -> "PipelineContext":
        context.vendor_context  = VendorContextLoader.load(context)
        context.history_context = DocumentHistoryLoader.load(context)
        context.erp_context     = ERPContextLoader.load(context)

        # Inject into normalized_doc so rules can use doc.get_org("vendor"), etc.
        if context.normalized_doc:
            context.normalized_doc.org_context.update({
                "vendor":  context.vendor_context,
                "history": context.history_context,
                "erp":     context.erp_context,
            })

        logger.debug(
            "[context_builder] Enriched org_context: vendor_loaded=%s "
            "history_runs=%s erp_connected=%s",
            bool(context.vendor_context),
            context.history_context.get("recent_run_count", 0),
            context.erp_context.get("erp_connected", False),
        )
        return context
