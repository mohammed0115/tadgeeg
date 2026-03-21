"""
Document Normalizer Factory.

Each document type has a dedicated normalizer that reads from the appropriate
Django model and returns a NormalizedDocument instance for rule processing.
"""
import logging
from apps.rule_engine.rules.base import NormalizedDocument

logger = logging.getLogger("rule_engine")


class BaseNormalizer:
    """Abstract base for document normalizers."""
    document_type: str = ""

    def normalize(self, document_id: str, organization_id: str) -> NormalizedDocument:
        raise NotImplementedError

    def _get_org_context(self, organization_id: str) -> dict:
        """Load organization-level context needed for rule evaluation."""
        try:
            from apps.authentication.models import Organization
            org = Organization.objects.get(id=organization_id)
            return {
                "registration_date": str(org.created_at.date()) if hasattr(org, 'created_at') else None,
                "fiscal_year_start_month": getattr(org, 'fiscal_year_start_month', 1),
                "approved_vendor_ids": [],  # extend as vendor registry grows
            }
        except Exception:
            return {}


class FallbackNormalizer(BaseNormalizer):
    """Fallback: creates a minimal NormalizedDocument from a document ID."""

    def normalize(self, document_id: str, organization_id: str) -> NormalizedDocument:
        try:
            from apps.auditing.models import AuditDocument
            doc = AuditDocument.objects.get(id=document_id)
            return NormalizedDocument(
                document_id=str(document_id),
                document_type=doc.selected_doc_type or "other",
                organization_id=str(organization_id),
                org_context=self._get_org_context(organization_id),
                typed_data=doc.ai_result or {},
            )
        except Exception as e:
            logger.warning(f"FallbackNormalizer failed for {document_id}: {e}")
            return NormalizedDocument(
                document_id=str(document_id),
                document_type="other",
                organization_id=str(organization_id),
            )


class DocumentNormalizerFactory:
    """Returns the appropriate normalizer for a document type."""

    _registry: dict = {}

    @classmethod
    def register(cls, document_type: str, normalizer_class):
        cls._registry[document_type] = normalizer_class

    @classmethod
    def get(cls, document_type: str) -> BaseNormalizer:
        normalizer_class = cls._registry.get(document_type, FallbackNormalizer)
        return normalizer_class()
