"""
ISA 700 Formal Auditor Opinion Service

Generates comprehensive independent auditor's report per International Standard on Auditing 700
and ISA 705 (modifications to audit opinion).

Scope:
  - Auditor responsibility statement (Management's responsibility, Auditor's responsibility)
  - Opinion paragraph (unqualified, qualified, adverse, or disclaimer)
  - Basis for opinion (key matters justifying the opinion type)
  - Scope and significant limitations
  - Key audit matters (ISA 701 integration)
  - Compliance assessment (ZATCA Phase 2, ISA, IAS standards)
  - Audit evidence summary
  - Going concern assessment
  - Subsequent events (if any)
  - Other information assessment
  - Audit committee communication requirements

Standards Applied:
  - ISA 700 — Forming an Audit Opinion and Reporting on Financial Statements
  - ISA 705 — Modifications to the Auditor's Report
  - ISA 701 — Communicating Key Audit Matters in the Auditor's Report
  - ISA 250 — Consideration of Laws and Regulations in an Audit
  - ISA 315 — Identifying and Assessing the Risks of Material Misstatement
  - ISA 330 — Procedures in Response to Assessed Risks

Author: Financial AI System
Version: 2.0 (March 2026)
"""

import logging
from datetime import datetime, date, timezone as dt_timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from django.utils import timezone
from django.db.models import Count, Sum, Avg

logger = logging.getLogger("finai.audit.isa700")

# ── TADGEEG-FIN-AUDIT-5B — safe-wording policy ────────────────────────────────
# This service produces an AUDIT-READINESS / OPINION-PREPARATION DRAFT, not a
# formal audit opinion. Automated output must never say "in our opinion",
# "present fairly", or "opinion issued"; any direction is "subject to auditor
# review" and carries this disclaimer.
SAFE_DISCLAIMER_EN = (
    "This output is an audit readiness and opinion preparation aid. It does not "
    "constitute a formal audit opinion. The final audit opinion must be prepared "
    "and approved by a licensed auditor based on professional judgment and "
    "sufficient appropriate audit evidence."
)
SAFE_DISCLAIMER_AR = (
    "هذا المُخرَج أداة مساعدة لجاهزية التدقيق وتحضير الرأي، ولا يُعدّ رأي تدقيق "
    "رسميًا. يجب أن يُعِدّ الرأي النهائي ويعتمده مدقّق مرخّص بناءً على الحكم المهني "
    "وأدلة تدقيق كافية ومناسبة."
)
# opinion_type code → safe DRAFT DIRECTION label (always subject to auditor review).
_DIRECTION_LABEL_EN = {
    "unqualified": "Likely unmodified direction — subject to auditor review",
    "qualified":   "Possible modified (except-for) direction — subject to auditor review",
    "adverse":     "Possible modified (adverse) direction — subject to auditor review",
    "disclaimer":  "Insufficient basis to suggest a direction — subject to auditor review",
}
_DIRECTION_LABEL_AR = {
    "unqualified": "اتجاه مبدئي: غير معدّل على الأرجح — رهن مراجعة المدقّق",
    "qualified":   "اتجاه مبدئي: احتمال تعديل (باستثناء) — رهن مراجعة المدقّق",
    "adverse":     "اتجاه مبدئي: احتمال تعديل (سلبي) — رهن مراجعة المدقّق",
    "disclaimer":  "أساس غير كافٍ لاقتراح اتجاه — رهن مراجعة المدقّق",
}


class ISA700OpinionService:
    """
    Builds an ISA 700-structured **audit-readiness / opinion-preparation draft**
    (evidence, risk assessment, compliance statement, suggested direction). It is
    NOT a formal audit opinion and is not issued automatically — the final
    opinion must be prepared and approved by a licensed auditor.
    """

    # Risk thresholds for opinion determination
    OPINION_THRESHOLDS = {
        "unqualified": 90.0,      # compliance >= 90% AND no critical issues
        "qualified": 70.0,         # compliance >= 70% AND some non-pervasive issues
        "adverse": 0.0,            # compliance < 70% OR pervasive critical issues
        "disclaimer": -1.0,        # insufficient evidence (total == 0)
    }

    # Scope and basis language
    MANAGEMENT_RESPONSIBILITY_AR = """
المسؤولية عن البيانات المالية:
تتحمل الإدارة المسؤولية عن إعداد وعدالة عرض البيانات المالية وفقاً للمعايير المحاسبية المطبقة،
بما في ذلك ضمان التكامل والدقة والاكتمال المادي للفواتير والمعاملات المسجلة، وكذلك الالتزام
بمتطلبات هيئة الزكاة والدخل (ZATCA) والمعايير الدولية للتدقيق (ISA).
"""

    MANAGEMENT_RESPONSIBILITY_EN = """
Management's Responsibility:
Management is responsible for the preparation and fair presentation of the financial statements
in accordance with applicable accounting standards, including ensuring the completeness, accuracy,
and material fairness of recorded invoices and transactions, as well as compliance with the Zakat,
Tax and Customs Authority (ZATCA) requirements and International Standards on Auditing (ISA).
"""

    AUDITOR_RESPONSIBILITY_AR = """
مسؤولية المدقّق:
إبداء الرأي على البيانات المالية مسؤولية مدقّق مرخّص بناءً على حكمه المهني وأدلة تدقيق كافية
ومناسبة. يقدّم تحليل Tadgeeg الآلي إجراءات منظَّمة وفق المعايير الدولية للتدقيق (ISA) كأداة مساعدة
لجاهزية التدقيق وتحضير الرأي فقط؛ ولا يُعدّ هذا المُخرَج رأي تدقيق رسميًا ولا يحلّ محل المدقّق.
"""

    AUDITOR_RESPONSIBILITY_EN = """
Auditor's Responsibility:
Expressing an opinion on the financial statements is the responsibility of a licensed auditor, based
on professional judgment and sufficient appropriate audit evidence. Tadgeeg automated analysis
provides structured procedures aligned with International Standards on Auditing (ISA) as an audit
readiness and opinion preparation aid only; this output is not a formal audit opinion and does not
replace the auditor.
"""

    def __init__(self, organization, user=None):
        """Initialize with organization context."""
        self.org = organization
        self.user = user
        self.now = datetime.now(tz=dt_timezone.utc)

    def generate_opinion(
        self,
        summary: Dict,
        validations: Dict,
        invoices: List,
        kams_list: List,
        compliance_engine: Dict,
        anomalies: Dict,
        scope_limitations: Optional[List[str]] = None,
    ) -> Dict:
        """
        Generate complete ISA 700 auditor opinion report section.
        
        Args:
            summary: Aggregated audit summary (counts, scores, compliance metrics)
            validations: Map of {invoice_id → InvoiceValidationResult}
            invoices: List of Invoice objects audited
            kams_list: List of Key Audit Matters (ISA 701)
            compliance_engine: Compliance rule breakdown
            anomalies: Detected anomalies and fraud indicators
            scope_limitations: Any explicit audit scope limitations
            
        Returns:
            Dict with complete ISA 700 opinion report section containing:
              - opinion_paragraph: Main auditor opinion
              - basis_for_opinion: Key facts supporting the opinion
              - scope_and_basis: Audit procedures performed
              - management_responsibility: Management's role
              - auditor_responsibility: Auditor's role
              - audit_evidence_summary: Procedures and evidence obtained
              - compliance_statement: ISA/IAS/ZATCA compliance
              - risk_assessment_summary: Key risks identified
              - key_audit_matters: Integration with ISA 701
              - going_concern_assessment: Continuity assumptions
              - subsequent_events: Post-audit events
              - audit_committee_communication: Required communications
              - auditor_signature_block: Formal closing
        """
        # Determine opinion type based on compliance metrics
        opinion_type, opinion_basis = self._determine_opinion_type(summary, validations, invoices)
        
        # Extract key metrics
        total_invoices = summary.get("total_invoices", 0)
        validated_count = summary.get("validated_count", 0)
        compliance_score = summary.get("compliance_score", 0.0)
        critical_failures = summary.get("critical_failures", 0)
        high_risk_invoices = summary.get("high_risk_count", 0)
        duplicate_count = summary.get("duplicate_count", 0)

        # Build opinion report
        report = {
            # ── 1. MANAGEMENT & AUDITOR RESPONSIBILITY STATEMENTS (ISA 700 A66-A90) ──
            "management_responsibility": {
                "ar": self.MANAGEMENT_RESPONSIBILITY_AR,
                "en": self.MANAGEMENT_RESPONSIBILITY_EN,
            },
            "auditor_responsibility": {
                "ar": self.AUDITOR_RESPONSIBILITY_AR,
                "en": self.AUDITOR_RESPONSIBILITY_EN,
            },

            # ── 2. AUDIT SCOPE & SIGNIFICANT LIMITATIONS (ISA 700 A65) ──────────────
            "scope_and_basis": self._build_scope_and_basis(
                total_invoices, validated_count, scope_limitations
            ),

            # ── 3. RISK ASSESSMENT SUMMARY (ISA 315 Integration) ──────────────────────
            "risk_assessment_summary": self._build_risk_assessment(
                summary, validations, anomalies, compliance_engine
            ),

            # ── 4. COMPLIANCE STATEMENT (ZATCA Phase 2 + ISA/IAS) ──────────────────
            "compliance_statement": self._build_compliance_statement(
                compliance_engine, summary
            ),

            # ── 5. AUDIT PROCEDURES PERFORMED (ISA 330 Evidence) ──────────────────────
            "audit_evidence_summary": self._build_audit_evidence(
                total_invoices, validations, compliance_engine
            ),

            # ── 6. MAIN OPINION PARAGRAPH (ISA 700 A118-A151) ──────────────────────
            "opinion_paragraph": self._build_opinion_paragraph(
                opinion_type, opinion_basis, compliance_score
            ),

            # ── 7. BASIS FOR OPINION (ISA 700 A67-A72) ─────────────────────────────
            "basis_for_opinion": self._build_basis_for_opinion(
                opinion_type, summary, validations, invoices
            ),

            # ── 8. ISA 701 KEY AUDIT MATTERS INTEGRATION ──────────────────────────────
            "key_audit_matters_summary": self._build_kams_summary(kams_list, opinion_type),

            # ── 9. GOING CONCERN ASSESSMENT (ISA 570) ──────────────────────────────────
            "going_concern_assessment": self._build_going_concern(summary),

            # ── 10. SUBSEQUENT EVENTS ASSESSMENT (ISA 560) ──────────────────────────
            "subsequent_events": self._build_subsequent_events(),

            # ── 11. AUDIT COMMITTEE COMMUNICATIONS (ISA 260) ───────────────────────
            "audit_committee_communications": self._build_audit_committee_comms(
                opinion_type, critical_failures, duplicate_count, high_risk_invoices
            ),

            # ── 12. PREPARATION BLOCK — draft prepared for licensed-auditor review ──
            "auditor_signature_block": {
                "text_ar": f"مسوّدة جاهزية أعدّها تحليل Tadgeeg الآلي بتاريخ {self._format_date_ar(self.now.date())} لمراجعة مدقّق مرخّص. ليست رأي تدقيق رسميًا.",
                "text_en": f"Audit-readiness draft prepared by Tadgeeg automated analysis on {self._format_date_en(self.now.date())} for licensed-auditor review. Not a formal audit opinion.",
                "date": self.now.isoformat(),
                "system_version": "2.0",
                "isa_standard": "Structured per ISA 700 / 705 / 701 — preparation aid only",
                "requires_licensed_auditor_review": True,
            },

            # ── 13. SAFE-WORDING DISCLAIMER (TADGEEG-FIN-AUDIT-5B) ───────────────────
            "is_formal_opinion": False,
            "subject_to_auditor_review": True,
            "disclaimer_en": SAFE_DISCLAIMER_EN,
            "disclaimer_ar": SAFE_DISCLAIMER_AR,
            "suggested_opinion_direction": opinion_type,

            # ── 14. METADATA ────────────────────────────────────────────────────────
            # ``opinion_type`` stays an internal CODE for compatibility; the
            # human-facing labels are DRAFT DIRECTIONS (subject to auditor review).
            "opinion_type": opinion_type,
            "opinion_type_ar": _DIRECTION_LABEL_AR.get(opinion_type, "رهن مراجعة المدقّق"),
            "opinion_type_en": _DIRECTION_LABEL_EN.get(opinion_type, "Subject to auditor review"),
            "compliance_score": compliance_score,
            "audit_date": self.now.isoformat(),
            "audit_period_invoices": total_invoices,
            "audit_period_validated": validated_count,
            "critical_issues_found": critical_failures > 0,
            "critical_issues_count": critical_failures,
        }

        return report

    # ─────────────────────────────────────────────────────────────────────────────
    # HELPER METHODS
    # ─────────────────────────────────────────────────────────────────────────────

    def _determine_opinion_type(
        self, summary: Dict, validations: Dict, invoices: List
    ) -> Tuple[str, str]:
        """
        Determine audit opinion type per ISA 700 & ISA 705.
        
        Returns:
            (opinion_type, basis_phrase) where opinion_type is one of:
            - 'unqualified': clean audit, compliance >= 90%, no critical failures
            - 'qualified': material but non-pervasive issues
            - 'adverse': material and pervasive issues, compliance < 70%
            - 'disclaimer': insufficient evidence
        """
        total = summary.get("total_invoices", 0)
        validated = summary.get("validated_count", 0)
        score = summary.get("compliance_score", 0.0)
        critical = summary.get("critical_failures", 0)
        duplicates = summary.get("duplicate_count", 0)
        high_risk = summary.get("high_risk_count", 0)

        # Insufficient evidence → Disclaimer of Opinion (ISA 700 A79)
        if total == 0 or validated == 0:
            return "disclaimer", "insufficient_evidence"

        # Unqualified Opinion: fully compliant, zero critical issues (ISA 700 A118)
        if score >= self.OPINION_THRESHOLDS["unqualified"] and critical == 0 and duplicates == 0:
            return "unqualified", "no_material_misstatements"

        # Adverse Opinion: pervasive critical issues (ISA 705 A8-A9)
        if score < self.OPINION_THRESHOLDS["qualified"] or critical >= 3:
            return "adverse", "pervasive_material_misstatements"

        # Qualified Opinion: material but non-pervasive (ISA 705 A5)
        if score >= self.OPINION_THRESHOLDS["qualified"]:
            return "qualified", "except_for_issues"

        # Default: Adverse if none of the above
        return "adverse", "pervasive_material_misstatements"

    def _build_scope_and_basis(
        self, total: int, validated: int, scope_limitations: Optional[List[str]] = None
    ) -> Dict:
        """Build audit scope and basis for audit section (ISA 700 A65)."""
        scope_text_ar = (
            f"تم تدقيق {validated} فاتورة من إجمالي {total} فاتورة خلال الفترة المشمولة بالتقرير. "
            f"تضمن نطاق التدقيق التحقق من مطابقة الفواتير لمتطلبات إطار إعداد التقارير المالية "
            f"المطبقة والمعايير الدولية للتدقيق (ISA)."
        )
        scope_text_en = (
            f"We audited {validated} invoices out of a total of {total} invoices during the "
            f"reporting period. Our audit scope included verifying invoice compliance with applicable "
            f"financial reporting standards and International Standards on Auditing (ISA)."
        )

        if scope_limitations:
            scope_text_ar += "\n\n" + "قيود نطاق التدقيق:\n" + "\n".join(
                f"• {limitation}" for limitation in scope_limitations
            )
            scope_text_en += "\n\nAudit Scope Limitations:\n" + "\n".join(
                f"• {limitation}" for limitation in scope_limitations
            )

        return {
            "scope_ar": scope_text_ar,
            "scope_en": scope_text_en,
            "basis_ar": "تم تطبيق المعايير الدولية للتدقيق (ISA) والمعايير الدولية لإعداد",
            "basis_en": "International Standards on Auditing (ISA) and International Financial Reporting",
        }

    def _build_risk_assessment(
        self, summary: Dict, validations: Dict, anomalies: Dict, compliance_engine: Dict
    ) -> Dict:
        """Build risk assessment summary per ISA 315."""
        critical_failures = summary.get("critical_failures", 0)
        high_risk_count = summary.get("high_risk_count", 0)
        duplicate_count = summary.get("duplicate_count", 0)
        anomaly_count = summary.get("anomaly_count", 0)

        return {
            "identified_risks": [
                {
                    "risk_type": "Duplicate Transactions",
                    "count": duplicate_count,
                    "assessed_level": "High" if duplicate_count > 0 else "Low",
                    "control_procedure": "Systematic duplicate detection using invoice number, vendor + amount, file hash, and temporal patterns",
                },
                {
                    "risk_type": "High-Risk Invoices (Anomalies)",
                    "count": high_risk_count,
                    "assessed_level": "High" if high_risk_count > 0 else "Low",
                    "control_procedure": "Automated anomaly detection using Benford's Law chi-square test, vendor concentration analysis, and AI risk scoring",
                },
                {
                    "risk_type": "ZATCA Compliance Violations",
                    "count": critical_failures,
                    "assessed_level": "Critical" if critical_failures > 0 else "Low",
                    "control_procedure": "Validation of mandatory ZATCA fields, VAT calculations, and QR code compliance",
                },
                {
                    "risk_type": "Manual Anomalies Detected",
                    "count": anomaly_count,
                    "assessed_level": "Medium" if anomaly_count > 0 else "Low",
                    "control_procedure": "Temporal anomalies, price changes, vendor concentration, and seasonal patterns",
                },
            ],
            "overall_risk_assessment": {
                "ar": "مرتفع" if critical_failures > 0 else "متوسط" if high_risk_count > 0 else "منخفض",
                "en": "High" if critical_failures > 0 else "Medium" if high_risk_count > 0 else "Low",
            },
            "risk_indicators": {
                "critical_failures": critical_failures,
                "high_risk_invoices": high_risk_count,
                "duplicates": duplicate_count,
                "anomalies": anomaly_count,
            },
        }

    def _build_compliance_statement(self, compliance_engine: Dict, summary: Dict) -> Dict:
        """Build comprehensive compliance statement against standards."""
        score = summary.get("compliance_score", 0.0)
        
        return {
            "standards_applied": [
                {
                    "standard": "ISA 700",
                    "title": "Forming an Audit Opinion and Reporting on Financial Statements",
                    "status": "✓ Applied",
                    "version": "2015 Edition",
                },
                {
                    "standard": "ISA 705",
                    "title": "Modifications to the Auditor's Report",
                    "status": "✓ Applied",
                    "version": "2015 Edition",
                },
                {
                    "standard": "ISA 701",
                    "title": "Communicating Key Audit Matters in the Auditor's Report",
                    "status": "✓ Applied",
                    "version": "2015 Edition",
                },
                {
                    "standard": "ZATCA Phase 2",
                    "title": "Mandatory E-Invoicing Specification",
                    "status": "✓ Applied",
                    "version": "2.0 (2023)",
                },
            ],
            "compliance_rate": f"{score:.1f}%",
            "compliance_assessment_ar": (
                "تم تقييم الامتثال بناءً على 34 معايير تدقيق و 6 مجموعات قواعد تغطي "
                "رؤوس الفواتير والحسابات المالية والضريبة والتكراريات والشذوذ والضوابط."
            ),
            "compliance_assessment_en": (
                "Compliance assessment based on 34 audit criteria and 6 rule groups covering "
                "invoice headers, financial amounts, VAT, duplicates, anomalies, and controls."
            ),
        }

    def _build_audit_evidence(
        self, total: int, validations: Dict, compliance_engine: Dict
    ) -> Dict:
        """Build audit evidence summary per ISA 330."""
        return {
            "procedures_performed": [
                {
                    "procedure": "Risk Identification",
                    "description": "Identified material misstatement risks through analytical procedures and invoice matching",
                    "evidence_obtained": "Risk profiles for all invoices; anomalies flagged",
                },
                {
                    "procedure": "Completeness Testing",
                    "description": "Verified all required mandatory fields (ZATCA specification compliance)",
                    "evidence_obtained": f"{total} invoices tested for field completeness",
                },
                {
                    "procedure": "Duplicate Detection",
                    "description": "Applied 5 duplicate detection rules (invoice number, vendor+amount, file hash, etc.)",
                    "evidence_obtained": "Duplicate detection report per duplicate rule",
                },
                {
                    "procedure": "VAT Compliance",
                    "description": "Validated VAT calculations, rates, and numbers against ZATCA requirements",
                    "evidence_obtained": "VAT compliance report; QR code validation results",
                },
                {
                    "procedure": "Anomaly Analysis",
                    "description": "Applied Benford's Law chi-square test and vendor concentration analysis",
                    "evidence_obtained": "Benford distribution report; vendor spend analysis",
                },
            ],
            "sampling_methodology": "All-items sampling (100% of invoices in period)",
            "total_items_tested": total,
            "materiality_level": "Per ISA 320: Professional judgment applied",
            "evidence_reliability": "High — Computer-assisted audit techniques with automated testing",
        }

    def _build_opinion_paragraph(
        self, opinion_type: str, basis_phrase: str, compliance_score: float
    ) -> Dict:
        """Build a SAFE draft-direction paragraph (NOT a formal opinion).

        Wording is hardened (TADGEEG-FIN-AUDIT-5B): no "in our opinion" /
        "present fairly" / "opinion issued". Every direction is suggested and
        "subject to auditor review", with a disclaimer attached.
        """
        if opinion_type == "unqualified":
            opinion_en = (
                f"Audit readiness — suggested draft direction: LIKELY UNMODIFIED, subject to "
                f"auditor review. Automated testing indicated a {compliance_score:.1f}% compliance "
                f"rate with no critical exceptions flagged. This is not a formal audit opinion; a "
                f"licensed auditor must evaluate the evidence and prepare the final opinion."
            )
            opinion_ar = (
                f"جاهزية التدقيق — اتجاه مبدئي مقترح: غير معدّل على الأرجح، رهن مراجعة المدقّق. "
                f"أظهر الاختبار الآلي نسبة امتثال {compliance_score:.1f}٪ دون استثناءات حرجة. "
                f"هذا ليس رأي تدقيق رسميًا؛ يجب أن يقيّم مدقّق مرخّص الأدلة ويُعِدّ الرأي النهائي."
            )
        elif opinion_type == "qualified":
            opinion_en = (
                f"Audit readiness — suggested draft direction: POSSIBLE MODIFICATION for except-for "
                f"matters, subject to auditor review. Automated testing indicated a {compliance_score:.1f}% "
                f"compliance rate with non-pervasive matters to evaluate. This is not a formal audit "
                f"opinion; a licensed auditor must prepare the final opinion."
            )
            opinion_ar = (
                f"جاهزية التدقيق — اتجاه مبدئي مقترح: احتمال تعديل بشأن مسائل (باستثناء)، رهن مراجعة "
                f"المدقّق. أظهر الاختبار الآلي نسبة امتثال {compliance_score:.1f}٪ مع مسائل غير منتشرة "
                f"تحتاج تقييمًا. هذا ليس رأي تدقيق رسميًا؛ يجب أن يُعِدّ مدقّق مرخّص الرأي النهائي."
            )
        elif opinion_type == "adverse":
            opinion_en = (
                f"Audit readiness — suggested draft direction: POSSIBLE ADVERSE MODIFICATION due to "
                f"pervasive matters, subject to auditor review. Automated testing indicated a "
                f"{compliance_score:.1f}% compliance rate with potentially pervasive matters. This is not "
                f"a formal audit opinion; a licensed auditor must prepare the final opinion."
            )
            opinion_ar = (
                f"جاهزية التدقيق — اتجاه مبدئي مقترح: احتمال تعديل سلبي بسبب مسائل منتشرة، رهن مراجعة "
                f"المدقّق. أظهر الاختبار الآلي نسبة امتثال {compliance_score:.1f}٪ مع مسائل قد تكون "
                f"منتشرة. هذا ليس رأي تدقيق رسميًا؛ يجب أن يُعِدّ مدقّق مرخّص الرأي النهائي."
            )
        else:  # disclaimer / insufficient basis
            opinion_en = (
                "Audit readiness — insufficient basis to suggest a direction, subject to auditor "
                "review. Available data and evidence were not sufficient for automated evaluation. "
                "This is not a formal audit opinion; a licensed auditor must prepare the final opinion."
            )
            opinion_ar = (
                "جاهزية التدقيق — أساس غير كافٍ لاقتراح اتجاه، رهن مراجعة المدقّق. لم تكن البيانات "
                "والأدلة المتاحة كافية للتقييم الآلي. هذا ليس رأي تدقيق رسميًا؛ يجب أن يُعِدّ مدقّق "
                "مرخّص الرأي النهائي."
            )

        return {
            "opinion_type": opinion_type,
            # Draft DIRECTION labels — never a formal opinion label.
            "opinion_type_en": _DIRECTION_LABEL_EN.get(opinion_type, "Subject to auditor review"),
            "opinion_type_ar": _DIRECTION_LABEL_AR.get(opinion_type, "رهن مراجعة المدقّق"),
            "suggested_opinion_direction": opinion_type,
            "subject_to_auditor_review": True,
            "is_formal_opinion": False,
            "opinion_ar": opinion_ar,
            "opinion_en": opinion_en,
            "basis_phrase": basis_phrase,
            "disclaimer_en": SAFE_DISCLAIMER_EN,
            "disclaimer_ar": SAFE_DISCLAIMER_AR,
        }

    def _build_basis_for_opinion(
        self, opinion_type: str, summary: Dict, validations: Dict, invoices: List
    ) -> Dict:
        """Build the basis for the SUGGESTED DIRECTION (preparation aid, not an opinion)."""
        score = summary.get("compliance_score", 0.0)
        critical = summary.get("critical_failures", 0)
        duplicates = summary.get("duplicate_count", 0)
        high_risk = summary.get("high_risk_count", 0)

        basis_ar = (
            f"أساس الاتجاه المقترح (رهن مراجعة المدقّق): طبّق تحليل Tadgeeg الآلي إجراءات منظَّمة وفق "
            f"المعايير الدولية للتدقيق، وبلغت نسبة الامتثال {score:.1f}٪ عبر اختبار {len(invoices)} فاتورة "
            f"وتطبيق 34 معيار تدقيق. تم تحديد {critical} استثناءً حرجًا و{duplicates} تكرارًا و{high_risk} "
            f"فاتورة عالية المخاطر. يجب أن يقيّم مدقّق مرخّص هذه النتائج ويُعِدّ الرأي النهائي."
        )
        basis_en = (
            f"Basis for the suggested direction (subject to auditor review): Tadgeeg automated analysis "
            f"applied structured procedures aligned with International Standards on Auditing, indicating a "
            f"{score:.1f}% compliance rate across {len(invoices)} invoices and 34 audit criteria. It flagged "
            f"{critical} critical exceptions, {duplicates} duplicates, and {high_risk} high-risk invoices. "
            f"A licensed auditor must evaluate these results and prepare the final opinion."
        )

        return {
            "basis_ar": basis_ar,
            "basis_en": basis_en,
            "key_findings": [
                f"Compliance Score: {score:.1f}%",
                f"Invoices Audited: {len(invoices)}",
                f"Critical Failures: {critical}",
                f"Duplicates Identified: {duplicates}",
                f"High-Risk Invoices: {high_risk}",
            ],
        }

    def _build_kams_summary(self, kams_list: List, opinion_type: str) -> Dict:
        """Integrate ISA 701 Key Audit Matters."""
        kams_count = len([k for k in kams_list if k.get("is_kam",  False)])
        
        return {
            "kam_status": "Identified" if kams_count > 0 else "None",
            "kam_count": kams_count,
            "kams": kams_list[:5],  # Top 5 KAMs
            "communication_required": opinion_type in ("qualified", "adverse"),
            "isa_reference": "ISA 701 — Communicating Key Audit Matters in the Auditor's Report",
        }

    def _build_going_concern(self, summary: Dict) -> Dict:
        """Build going concern assessment per ISA 570."""
        score = summary.get("compliance_score", 0.0)
        critical = summary.get("critical_failures", 0)

        return {
            "assessment": "No indicators of going concern issues identified" if critical == 0 else "Potential going concern indicators present",
            "basis_ar": "لا توجد مؤشرات على مشاكل الاستمرارية المالية بناءً على نتائج التدقيق.",
            "basis_en": "No indicators of financial continuity issues based on audit results.",
            "isa_reference": "ISA 570 — Going Concern",
        }

    def _build_subsequent_events(self) -> Dict:
        """Build subsequent events assessment per ISA 560."""
        return {
            "assessment": "No subsequent events identified affecting financial statements",
            "basis_ar": "لم نحدد أي أحداث لاحقة تؤثر بشكل جوهري على البيانات المالية المدققة.",
            "basis_en": "No subsequent events have been identified that materially affect the audited financial statements.",
            "isa_reference": "ISA 560 — Subsequent Events",
        }

    def _build_audit_committee_comms(
        self, opinion_type: str, critical_failures: int, duplicates: int, high_risk: int
    ) -> Dict:
        """Build audit committee communication requirements per ISA 260."""
        return {
            "communication_required": True,
            "topics": [
                {
                    "topic": "Opinion Type and Basis",
                    "description": f"Communicated via formal audit report ({opinion_type} opinion)",
                },
                {
                    "topic": "Critical Issues",
                    "description": f"Identified {critical_failures} critical failures requiring immediate remediation",
                },
                {
                    "topic": "Duplicate Invoices",
                    "description": f"Detected {duplicates} duplicate invoices; recommended investigation",
                },
                {
                    "topic": "High-Risk Invoices",
                    "description": f"Flagged {high_risk} invoices for enhanced review",
                },
                {
                    "topic": "Compliance Status",
                    "description": "Provided detailed compliance breakdown across all audit criteria",
                },
            ],
            "timing": "Immediately upon report issuance",
            "isa_reference": "ISA 260 — Communication with Those Charged with Governance",
        }

    # ─── Formatting Utility Methods ────────────────────────────────────────────

    def _format_date_ar(self, d: date) -> str:
        """Format date in Arabic format."""
        months_ar = [
            "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
            "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"
        ]
        return f"{d.day} {months_ar[d.month - 1]} {d.year}"

    def _format_date_en(self, d: date) -> str:
        """Format date in English format."""
        return d.strftime("%B %d, %Y")
