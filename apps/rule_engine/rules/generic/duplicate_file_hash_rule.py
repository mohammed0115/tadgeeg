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
            from apps.documents.models import Document
            file_hash = doc.file_hash

            # Check for duplicate by file_hash stored in extracted_data.structured_data
            exists = Document.objects.filter(
                organization_id=doc.organization_id,
                extracted_data__structured_data__file_hash=file_hash,
            ).exclude(id=doc.document_id).exists()

            if exists:
                return self._fail(
                    "Identical file content already uploaded in this organisation.",
                    "تم رفع ملف بنفس المحتوى مسبقًا في هذه المنظمة.",
                    evidence=[EvidenceItem(
                        evidence_type="comparison",
                        field_name="file_hash",
                        field_name_ar="بصمة الملف",
                        expected_value="Unique hash",
                        actual_value=file_hash,
                        description="Duplicate file detected via content hash.",
                        description_ar="تم اكتشاف ملف مكرر عبر بصمة المحتوى.",
                    )]
                )

            return self._pass(
                "File hash is unique — no identical file found.",
                "بصمة الملف فريدة — لا يوجد ملف مطابق.",
            )
        except Exception as e:
            return self._error(e)
