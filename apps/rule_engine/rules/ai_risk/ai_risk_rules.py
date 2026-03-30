"""
AI-R01 – AI-R08 — AI-assisted and statistical risk detection rules.
These rules operate on pre-computed AI extraction fields in NormalizedDocument
and apply generically across all document types.
"""
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem


class LowOCRConfidenceRule(AuditRuleBase):
    """AI-R01 — Flags documents where OCR extraction confidence is below threshold."""
    rule_code = "AI-R01"
    rule_name_en = "Low OCR Confidence Score"
    rule_name_ar = "درجة ثقة منخفضة في استخراج النص الآلي"
    default_severity = "high"
    rule_type = "risk"

    FAIL_THRESHOLD = 0.70
    WARN_THRESHOLD = 0.85

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.ocr_confidence is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        fail_t = float(self.get_config("fail_threshold", self.FAIL_THRESHOLD))
        warn_t = float(self.get_config("warn_threshold", self.WARN_THRESHOLD))
        conf = float(doc.ocr_confidence)

        evidence = [EvidenceItem(
            evidence_type="statistical",
            field_name="ocr_confidence",
            field_name_ar="درجة ثقة الاستخراج",
            expected_value=f">= {warn_t:.0%}",
            actual_value=f"{conf:.1%}",
            description=f"OCR confidence: {conf:.1%}",
            description_ar=f"درجة ثقة الاستخراج: {conf:.1%}",
        )]

        if conf < fail_t:
            return self._fail(
                f"OCR confidence {conf:.1%} is critically low (threshold: {fail_t:.0%}). "
                "Data extracted from this document may be unreliable.",
                f"درجة ثقة الاستخراج {conf:.1%} منخفضة جداً (الحد: {fail_t:.0%}). "
                "البيانات المستخرجة قد لا تكون موثوقة.",
                evidence=evidence,
            )
        if conf < warn_t:
            return self._warning(
                f"OCR confidence {conf:.1%} is below recommended threshold ({warn_t:.0%}). "
                "Manual verification is recommended.",
                f"درجة ثقة الاستخراج {conf:.1%} أقل من المستوى الموصى به ({warn_t:.0%}). "
                "يُنصح بالمراجعة اليدوية.",
                evidence=evidence,
            )
        return self._pass(
            f"OCR confidence {conf:.1%} is acceptable.",
            f"درجة ثقة الاستخراج {conf:.1%} مقبولة.",
        )


class HandwrittenDocumentRule(AuditRuleBase):
    """AI-R02 — Handwritten documents carry higher fraud and extraction risk."""
    rule_code = "AI-R02"
    rule_name_en = "Handwritten Document Detected"
    rule_name_ar = "مستند مكتوب بخط اليد"
    default_severity = "medium"
    rule_type = "risk"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        is_handwritten = doc.is_handwritten or doc.get("is_handwritten", False)

        if is_handwritten:
            return self._warning(
                "Document appears to be handwritten. "
                "Handwritten documents have higher fraud risk and lower OCR accuracy.",
                "يبدو أن المستند مكتوب بخط اليد. "
                "المستندات المكتوبة بخط اليد تحمل مخاطر احتيال أعلى ودقة استخراج أقل.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="is_handwritten",
                    field_name_ar="مكتوب بخط اليد",
                    expected_value=False,
                    actual_value=True,
                    description="Document classified as handwritten by AI extraction.",
                    description_ar="المستند مصنَّف كمكتوب بخط اليد بواسطة نظام الاستخراج.",
                )]
            )
        return self._pass(
            "Document is machine-printed — standard extraction quality.",
            "المستند مطبوع — جودة الاستخراج معيارية.",
        )


class DocumentAlterationRule(AuditRuleBase):
    """AI-R03 — Detects documents with signs of alteration or tampering."""
    rule_code = "AI-R03"
    rule_name_en = "Document Alteration Detected"
    rule_name_ar = "اكتشاف تعديل في المستند"
    default_severity = "critical"
    rule_type = "risk"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        has_alterations = doc.get("has_alterations", False)

        if has_alterations:
            return self._fail(
                "Document shows signs of alteration or tampering. "
                "This is a critical fraud indicator requiring immediate investigation.",
                "يُظهر المستند علامات تعديل أو تلاعب. "
                "هذا مؤشر احتيال حرج يستلزم تحقيقاً فورياً.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="has_alterations",
                    field_name_ar="وجود تعديلات",
                    expected_value=False,
                    actual_value=True,
                    description="AI system flagged document alterations.",
                    description_ar="نظام الذكاء الاصطناعي رصد تعديلات في المستند.",
                )]
            )
        return self._pass(
            "No document alterations detected.",
            "لم يتم اكتشاف أي تعديلات في المستند.",
        )


class DocumentClarityRule(AuditRuleBase):
    """AI-R04 — Poor document clarity reduces audit reliability."""
    rule_code = "AI-R04"
    rule_name_en = "Document Clarity Issue"
    rule_name_ar = "مشكلة في وضوح المستند"
    default_severity = "medium"
    rule_type = "risk"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.get("is_clear") is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        is_clear = doc.get("is_clear", True)

        if not is_clear:
            return self._warning(
                "Document image quality is poor or unclear. "
                "Low-clarity documents may lead to extraction errors and audit gaps.",
                "جودة صورة المستند رديئة أو غير واضحة. "
                "المستندات غير الواضحة قد تؤدي إلى أخطاء استخراج وثغرات تدقيق.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="is_clear",
                    field_name_ar="وضوح المستند",
                    expected_value=True,
                    actual_value=False,
                    description="Document clarity flag set to False by AI system.",
                    description_ar="علامة وضوح المستند مُعيَّنة على False من نظام الذكاء الاصطناعي.",
                )]
            )
        return self._pass("Document clarity is acceptable.", "وضوح المستند مقبول.")


class BenfordsLawRule(AuditRuleBase):
    """AI-R05 — Benford's Law digit distribution analysis for fraud detection."""
    rule_code = "AI-R05"
    rule_name_en = "Benford's Law Anomaly Detected"
    rule_name_ar = "اكتشاف شذوذ في قانون بنفورد"
    default_severity = "high"
    rule_type = "anomaly"

    CRITICAL_MAD = 0.015   # Mean Absolute Deviation critical threshold
    WARNING_MAD  = 0.010   # Warning threshold

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        # Works on bank statements (pre-computed) or any doc with amount list
        return (doc.get("benford_deviation") is not None or
                len(doc.get("transactions") or []) >= 30)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        critical_mad = float(self.get_config("critical_mad", self.CRITICAL_MAD))
        warning_mad  = float(self.get_config("warning_mad",  self.WARNING_MAD))

        # Use pre-computed MAD value if available
        mad = doc.get("benford_deviation")

        if mad is None:
            # Compute from transaction amounts
            try:
                amounts = [abs(float(tx.get("amount", 0) or 0))
                           for tx in (doc.get("transactions") or [])
                           if tx.get("amount") not in (None, 0, "")]
                if len(amounts) < 30:
                    return self._skipped("Insufficient transactions for Benford's Law analysis (min 30).")

                from collections import Counter
                import math
                expected = {str(d): math.log10(1 + 1/d) for d in range(1, 10)}
                first_digits = [str(int(str(abs(a)).lstrip("0.").lstrip("0")[0]))
                                for a in amounts if str(abs(a)).replace(".", "").replace("0", "")]
                counter = Counter(first_digits)
                total = len(first_digits)
                if total == 0:
                    return self._skipped("No valid amounts for Benford analysis.")

                observed = {d: counter.get(d, 0) / total for d in [str(i) for i in range(1, 10)]}
                mad = sum(abs(observed.get(d, 0) - expected[d]) for d in expected) / 9
            except Exception:
                return self._skipped("Error computing Benford distribution.")

        mad = float(mad)
        evidence = [EvidenceItem(
            evidence_type="statistical",
            field_name="benford_deviation",
            field_name_ar="انحراف قانون بنفورد",
            expected_value=f"MAD < {warning_mad}",
            actual_value=f"MAD = {mad:.4f}",
            description=f"Mean Absolute Deviation from Benford's Law: {mad:.4f}",
            description_ar=f"متوسط الانحراف المطلق عن قانون بنفورد: {mad:.4f}",
        )]

        if mad >= critical_mad:
            return self._fail(
                f"Benford's Law: MAD = {mad:.4f} exceeds critical threshold {critical_mad}. "
                "Digit distribution is statistically inconsistent — high fraud risk.",
                f"قانون بنفورد: MAD = {mad:.4f} يتجاوز الحد الحرج {critical_mad}. "
                "توزيع الأرقام غير متسق إحصائياً — مخاطر احتيال عالية.",
                evidence=evidence,
            )
        if mad >= warning_mad:
            return self._warning(
                f"Benford's Law: MAD = {mad:.4f} exceeds warning threshold {warning_mad}. "
                "Some digit distribution irregularity detected.",
                f"قانون بنفورد: MAD = {mad:.4f} يتجاوز حد التحذير {warning_mad}. "
                "رُصد بعض اللاانتظام في توزيع الأرقام.",
                evidence=evidence,
            )
        return self._pass(
            f"Benford's Law: digit distribution is normal (MAD = {mad:.4f}).",
            f"قانون بنفورد: توزيع الأرقام طبيعي (MAD = {mad:.4f}).",
        )


class HighRiskScoreRule(AuditRuleBase):
    """AI-R06 — Document risk score from AI assessment exceeds safe threshold."""
    rule_code = "AI-R06"
    rule_name_en = "AI Risk Score Exceeds Threshold"
    rule_name_ar = "درجة مخاطر الذكاء الاصطناعي تتجاوز الحد"
    default_severity = "high"
    rule_type = "risk"

    DEFAULT_WARN_THRESHOLD  = 50.0
    DEFAULT_FAIL_THRESHOLD  = 75.0

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.get("risk_score") is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        warn_t = float(self.get_config("warn_threshold", self.DEFAULT_WARN_THRESHOLD))
        fail_t = float(self.get_config("fail_threshold", self.DEFAULT_FAIL_THRESHOLD))
        score = float(doc.get("risk_score", 0))

        evidence = [EvidenceItem(
            evidence_type="statistical",
            field_name="risk_score",
            field_name_ar="درجة المخاطر",
            expected_value=f"< {warn_t}",
            actual_value=score,
            description=f"AI-assigned risk score: {score}",
            description_ar=f"درجة المخاطر المحسوبة بالذكاء الاصطناعي: {score}",
        )]

        if score >= fail_t:
            return self._fail(
                f"AI risk score {score} exceeds critical threshold {fail_t}. "
                "Document requires immediate manual review.",
                f"درجة المخاطر {score} تتجاوز الحد الحرج {fail_t}. "
                "يتطلب المستند مراجعة يدوية فورية.",
                evidence=evidence,
            )
        if score >= warn_t:
            return self._warning(
                f"AI risk score {score} exceeds warning threshold {warn_t}.",
                f"درجة المخاطر {score} تتجاوز حد التحذير {warn_t}.",
                evidence=evidence,
            )
        return self._pass(
            f"AI risk score {score} is within acceptable range.",
            f"درجة المخاطر {score} ضمن النطاق المقبول.",
        )


class EmptyAIExtractionRule(AuditRuleBase):
    """AI-R07 — Warns when AI extraction returned no structured data."""
    rule_code = "AI-R07"
    rule_name_en = "AI Extraction Returned No Data"
    rule_name_ar = "استخراج الذكاء الاصطناعي لم يُعِد بيانات"
    default_severity = "medium"
    rule_type = "risk"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        extracted = doc.get("extracted_data") or {}
        ai_summary = doc.get("ai_summary") or ""

        if not extracted and not ai_summary:
            return self._warning(
                "AI extraction returned no structured data and no summary. "
                "Document may be unprocessable or in an unsupported format.",
                "استخراج الذكاء الاصطناعي لم يُعِد بيانات منظمة أو ملخصاً. "
                "قد يكون المستند غير قابل للمعالجة أو بتنسيق غير مدعوم.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="extracted_data",
                    field_name_ar="البيانات المستخرجة",
                    expected_value="Non-empty extraction result",
                    actual_value={},
                    description="AI extraction result is empty.",
                    description_ar="نتيجة الاستخراج بالذكاء الاصطناعي فارغة.",
                )]
            )
        return self._pass(
            "AI extraction produced structured data.",
            "استخراج الذكاء الاصطناعي أنتج بيانات منظمة.",
        )


class DuplicateContentFingerprintRule(AuditRuleBase):
    """AI-R08 — Detects documents with the same file hash (exact duplicate content)."""
    rule_code = "AI-R08"
    rule_name_en = "Duplicate Document Content Fingerprint"
    rule_name_ar = "بصمة محتوى المستند مكررة"
    default_severity = "critical"
    rule_type = "anomaly"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        is_dup = doc.get("is_duplicate", False)
        dup_of = doc.get("duplicate_of_id") or doc.get("duplicate_of") or ""
        file_hash = doc.file_hash or doc.get("file_hash") or ""

        if is_dup:
            return self._fail(
                f"Document is a duplicate of an existing record "
                f"(duplicate_of: {dup_of or 'unknown'}). "
                "Duplicate submissions may indicate billing fraud or data entry errors.",
                f"المستند مكرر لسجل موجود "
                f"(مكرر من: {dup_of or 'غير معروف'}). "
                "التقديم المكرر قد يدل على احتيال في الفوترة أو أخطاء إدخال.",
                evidence=[EvidenceItem(
                    evidence_type="reference",
                    field_name="is_duplicate",
                    field_name_ar="محتوى مكرر",
                    expected_value=False,
                    actual_value=True,
                    description=f"Duplicate of document {dup_of}. File hash: {file_hash[:16]}...",
                    description_ar=f"مكرر من المستند {dup_of}. بصمة الملف: {file_hash[:16]}...",
                )]
            )
        return self._pass(
            "Document content fingerprint is unique.",
            "بصمة محتوى المستند فريدة.",
        )
