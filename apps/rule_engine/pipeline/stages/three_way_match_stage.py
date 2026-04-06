"""
ThreeWayMatchStage — Stage 2.5 of AuditPipelineV2.

Runs between ContextBuilderStage (Stage 2) and RuleEngineStage (Stage 3).

Resolves the PO ↔ Invoice ↔ GRN triplet for the current document and
populates context.three_way_match with the serialised MatchResult dict.

The match result is also attached to the NormalizedDocument instance as
``doc._pipeline_context`` so that CDR-02 (ThreeWayMatchRule) can access
it during rule evaluation without an extra query.

Skips gracefully when:
  • The document type is not one of the three procurement types.
  • The NormalizedDocument is not yet available (normalizer failed).
  • ThreeWayMatchService raises (service failure does not abort pipeline).

Populates: context.three_way_match  (dict or empty dict)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.rule_engine.pipeline.stages.base import BaseStage

if TYPE_CHECKING:
    from apps.rule_engine.pipeline.v2.context import PipelineContext

logger = logging.getLogger("rule_engine.pipeline")

__all__ = ["ThreeWayMatchStage"]

# Document types that participate in procurement three-way matching.
_PROCUREMENT_TYPES = frozenset({
    "purchase_order",
    "invoice",
    "goods_receipt",
    "grn",
})


class ThreeWayMatchStage(BaseStage):
    """
    Resolves and runs the three-way match for procurement documents.
    Populates: context.three_way_match
    """

    name = "three_way_match"

    def should_skip(self, context: "PipelineContext") -> bool:
        """Skip for document types that are not part of the procurement cycle."""
        return context.document_type not in _PROCUREMENT_TYPES

    def _run(self, context: "PipelineContext") -> "PipelineContext":
        doc = context.normalized_doc
        if doc is None:
            logger.warning("[three_way_match] No normalized_doc; stage skipped.")
            context.three_way_match = {}
            return context

        try:
            from apps.rule_engine.services.three_way_match import ThreeWayMatchService

            service = ThreeWayMatchService()
            result = service.match_from_document(doc)

            if result is None:
                logger.info(
                    "[three_way_match] No triplet found for doc=%s type=%s",
                    context.document_id, context.document_type,
                )
                context.three_way_match = {}
                return context

            match_dict = result.to_dict()
            context.three_way_match = match_dict

            # Attach context reference so CDR-02 can read it without extra lookups.
            doc._pipeline_context = context  # type: ignore[attr-defined]

            logger.info(
                "[three_way_match] status=%s score=%.2f po=%s invoice=%s grn=%s",
                result.status.value,
                result.match_score,
                result.po_id,
                result.invoice_id,
                result.grn_id,
            )

        except Exception as exc:
            logger.warning("[three_way_match] Service failed (skipped): %s", exc)
            context.three_way_match = {}

        return context
