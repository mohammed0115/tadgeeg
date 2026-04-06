"""
DocumentNormalizerStage — Stage 1 of AuditPipeline V2.

Converts the raw Django model instance into a NormalizedDocument that all
downstream stages operate on. Wraps the existing DocumentNormalizerFactory
so no normaliser code is duplicated.

This is a CriticalStage: if normalisation fails, the pipeline aborts because
every subsequent stage depends on context.normalized_doc.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.rule_engine.pipeline.stages.base import CriticalStage
from apps.rule_engine.normalizers import DocumentNormalizerFactory

if TYPE_CHECKING:
    from apps.rule_engine.pipeline.v2.context import PipelineContext

logger = logging.getLogger("rule_engine.pipeline")

__all__ = ["DocumentNormalizerStage"]


class DocumentNormalizerStage(CriticalStage):
    """
    Normalises the raw document model into a NormalizedDocument.
    Populates: context.normalized_doc
    """

    name = "normalizer"

    def _run(self, context: "PipelineContext") -> "PipelineContext":
        normalizer = DocumentNormalizerFactory.get(context.document_type)
        context.normalized_doc = normalizer.normalize(
            context.document_id,
            context.organization_id,
        )
        logger.debug(
            "[normalizer] Normalised doc_id=%s type=%s ocr_confidence=%s",
            context.document_id,
            context.document_type,
            getattr(context.normalized_doc, "ocr_confidence", "n/a"),
        )
        return context
