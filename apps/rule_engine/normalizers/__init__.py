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
            from apps.authentication.models import Organization, OrganizationSettings
            org = Organization.objects.get(id=organization_id)
            financial = {}
            try:
                settings = OrganizationSettings.objects.get(organization=org)
                financial = settings.financial or {}
            except OrganizationSettings.DoesNotExist:
                pass
            return {
                "registration_date": str(org.created_at.date()) if hasattr(org, 'created_at') else None,
                "fiscal_year_start_month": getattr(org, 'fiscal_year_start_month', 1),
                "approved_vendor_ids": financial.get("approved_vendor_ids", []),
                "blocked_vendor_ids": financial.get("blocked_vendor_ids", []),
                "dual_approval_threshold": financial.get("dual_approval_threshold", 100000.0),
                "expected_employee_count": financial.get("expected_employee_count", None),
                "expense_policy_limits": financial.get("expense_policy_limits", {}),
                "expense_policy_limit": financial.get("expense_policy_limit", 5000.0),
                "po_approval_threshold": financial.get("po_approval_threshold", 50000.0),
                "payment_approval_threshold": financial.get("payment_approval_threshold", 50000.0),
                "aml_threshold": financial.get("aml_threshold", 60000.0),
                "large_invoice_threshold": financial.get("large_invoice_threshold", 10000.0),
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


# ── Auto-register all normalizers ─────────────────────────────────────────────
# Each module calls DocumentNormalizerFactory.register() at import time.
# Importing them here ensures the registry is populated whenever this
# package is imported (e.g. from audit_pipeline.py).
from apps.rule_engine.normalizers import invoice_normalizer          # noqa: E402, F401
from apps.rule_engine.normalizers import purchase_order_normalizer   # noqa: E402, F401
from apps.rule_engine.normalizers import bank_statement_normalizer   # noqa: E402, F401
from apps.rule_engine.normalizers import payroll_normalizer          # noqa: E402, F401
from apps.rule_engine.normalizers import expense_normalizer          # noqa: E402, F401
from apps.rule_engine.normalizers import tax_return_normalizer       # noqa: E402, F401
from apps.rule_engine.normalizers import fixed_asset_normalizer      # noqa: E402, F401
from apps.rule_engine.normalizers import sales_receipt_normalizer    # noqa: E402, F401
from apps.rule_engine.normalizers import grn_normalizer              # noqa: E402, F401
from apps.rule_engine.normalizers import payment_normalizer          # noqa: E402, F401
