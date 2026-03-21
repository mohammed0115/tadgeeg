"""DUP-04: Duplicate File Hash"""
import logging
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem

logger = logging.getLogger("rule_engine")

class DuplicateFileHashRule(AuditRuleBase):
    rule_code = "DUP-04"
    rule_name_en = "Duplicate File Hash"
    rule_name_ar = "تكرار بصمة الملف"
    default_severity = "high"
    rule_type = "anomaly"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(doc.file_hash)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            from apps.invoices.models import Invoice
            from apps.auditing.models import AuditDocument
            file_hash = doc.file_hash

            # Check across invoices
            inv_dup = Invoice.objects.filter(
                organization_id=doc.organization_id,
                file_hash=file_hash,
            ).exclude(id=doc.document_id).first()

            if inv_dup:
                return self._fail(
                    f"Identical file already exists (Invoice #{inv_dup.invoice_number}).",
                    f"ملف مطابق موجود مسبقًا (فاتورة #{inv_dup.invoice_number}).",
                    evidence=[EvidenceItem(
                        evidence_type="comparison",
                        field_name="file_hash",
                        field_name_ar="بصمة الملف",
                        expected_value="Unique hash",
                        actual_value=file_hash,
                        description=f"Duplicate of invoice {inv_dup.id}",
                        description_ar=f"مكرر للفاتورة {inv_dup.id}",
                    )]
                )

            # Check across audit documents
            audit_dup = AuditDocument.objects.filter(
                ai_result__file_hash=file_hash
            ).exclude(id=doc.document_id).first()

            if audit_dup:
                return self._fail(
                    f"Identical file already uploaded as document '{audit_dup.original_name}'.",
                    f"الملف مكرر، تم رفعه مسبقًا باسم '{audit_dup.original_name}'.",
                    evidence=[EvidenceItem(
                        evidence_type="comparison",
                        field_name="file_hash",
                        field_name_ar="بصمة الملف",
                        expected_value="Unique hash",
                        actual_value=file_hash,
                        description=f"Duplicate of audit document {audit_dup.id}",
                        description_ar=f"مكرر للمستند {audit_dup.id}",
                    )]
                )

            return self._pass(
                "File hash is unique — no identical file found.",
                "بصمة الملف فريدة — لا يوجد ملف مطابق.",
            )
        except Exception as e:
            return self._error(e)
