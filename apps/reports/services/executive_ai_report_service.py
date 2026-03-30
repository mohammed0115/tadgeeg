"""
🎯 Executive AI Report Service
محرك توليد التقارير التنفيذية للإدارة العليا
يدعم جميع أنواع المستندات (PO, Invoice, Bank Statement, Contract, etc.)
"""

from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime


class DocumentType(Enum):
    """أنواع المستندات المدعومة"""
    PURCHASE_ORDER = "purchase_order"
    INVOICE = "invoice"
    BANK_STATEMENT = "bank_statement"
    CONTRACT = "contract"
    EXPENSE_REPORT = "expense_report"
    JOURNAL_ENTRY = "journal_entry"


class RiskLevel(Enum):
    """مستويات المخاطرة"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class FailedRule:
    """معلومات القاعدة المخالفة"""
    code: str
    name_ar: str
    name_en: str
    reason: str
    severity: str  # Critical, High, Medium, Low
    blocks_approval: bool
    impact_ar: Optional[str] = None
    impact_en: Optional[str] = None


@dataclass
class DocumentAuditData:
    """بيانات تدقيق المستند الكاملة"""
    document_type: DocumentType
    document_id: str
    document_number: str
    company: str
    total_amount: float
    compliance_score: int  # 0-100
    risk_score: float  # 0-100
    risk_level: RiskLevel
    rules_passed: int
    rules_failed: int
    failed_rules: List[FailedRule]
    currency: str = "SAR"
    supplier_name: Optional[str] = None
    supplier_vat_valid: Optional[bool] = None
    zatca_compliance: Optional[int] = None  # 0-100 (for invoices)
    audit_date: datetime = None
    auditor_name: str = "نظام التدقيق الذكي"
    custom_fields: Dict[str, Any] = None


class ExecutiveAIReportGenerator:
    """
    محرك توليد التقارير التنفيذية الاحترافية
    Career: Big4 Auditor + AI Analyst
    Language: العربية الفصحى الواضحة
    Audience: CFO / Managing Director
    """

    def __init__(self):
        self.document_context = {
            DocumentType.PURCHASE_ORDER: {
                "ar": "أمر شراء",
                "en": "Purchase Order",
                "risk_factors": ["عدم الموافقة", "تجاوز الميزانية", "مورد غير موثوق"],
                "decision_impact": "تأثير مباشر على الالتزامات المالية والمخزون"
            },
            DocumentType.INVOICE: {
                "ar": "فاتورة",
                "en": "Invoice",
                "risk_factors": ["ضريبة غير صحيحة", "مورد مريب", "تكرار", "QR غير صالح"],
                "decision_impact": "تأثير على التدفقات النقدية والالتزامات الضريبية"
            },
            DocumentType.BANK_STATEMENT: {
                "ar": "كشف بنكي",
                "en": "Bank Statement",
                "risk_factors": ["عدم المطابقة", "معاملات مريبة", "أرصدة سالبة غير متوقعة"],
                "decision_impact": "تأثير على التقارير المالية والسيولة النقدية"
            },
            DocumentType.CONTRACT: {
                "ar": "عقد",
                "en": "Contract",
                "risk_factors": ["شروط غير واضحة", "مبالغ غير محددة", "توقيعات ناقصة"],
                "decision_impact": "تأثير على الالتزامات القانونية والمالية"
            },
            DocumentType.EXPENSE_REPORT: {
                "ar": "تقرير مصروفات",
                "en": "Expense Report",
                "risk_factors": ["فواتير مفقودة", "مصروفات شخصية", "عملات مختلطة"],
                "decision_impact": "تأثير على النتائج المالية والامتثال الضريبي"
            }
        }

    # ------------------------------------------------------------------
    # Bilingual helper
    # ------------------------------------------------------------------
    @staticmethod
    def _t(ar: str, en: str, language: str) -> str:
        """Return the English string when language='en', Arabic otherwise."""
        return en if language == "en" else ar

    def generate_report(self, audit_data: DocumentAuditData, language: str = "ar") -> Dict[str, str]:
        """
        Generate the full executive report.
        :param audit_data: Audit data object.
        :param language: 'ar' (default) or 'en'.
        Returns: dict with all report sections.
        """
        return {
            "executive_summary": self._generate_executive_summary(audit_data, language),
            "key_findings": self._generate_key_findings(audit_data, language),
            "risk_interpretation": self._generate_risk_interpretation(audit_data, language),
            "business_impact": self._generate_business_impact(audit_data, language),
            "decision": self._generate_decision(audit_data, language),
            "immediate_actions": self._generate_immediate_actions(audit_data, language),
            "process_improvements": self._generate_process_improvements(audit_data, language),
            "ai_insight": self._generate_ai_insight(audit_data, language)
        }

    def _generate_executive_summary(self, audit_data: DocumentAuditData, language: str = "ar") -> str:
        """1 — Executive Summary."""
        t = lambda ar, en: self._t(ar, en, language)
        doc_type = self.document_context[audit_data.document_type][language if language in ("ar", "en") else "ar"]
        compliance = audit_data.compliance_score
        risk = audit_data.risk_score
        amount = self._format_amount(audit_data.total_amount, language)

        if audit_data.rules_failed == 0 and compliance >= 95:
            status = t("✅ **ممتاز** — يمكن الاعتماد الفوري", "✅ **Excellent** — Ready for immediate approval")
        elif audit_data.rules_failed > 0 and any(r.blocks_approval for r in audit_data.failed_rules):
            status = t("❌ **مرفوض** — يتطلب تصحيح فوري", "❌ **Rejected** — Requires immediate correction")
        elif compliance >= 85:
            status = t("⚠️ **مشروط** — يمكن الاعتماد مع مراقبة", "⚠️ **Conditional** — Approval with monitoring")
        else:
            status = t("🔴 **ضعيف** — يتطلب مراجعة شاملة", "🔴 **Weak** — Requires comprehensive review")

        if language == "en":
            summary = f"""{status}

{doc_type} #{audit_data.document_number} — {amount}.

Compliance score: {compliance}%{'.' if audit_data.rules_failed == 0 else f', with {audit_data.rules_failed} violation(s) that directly affect approval validity.'}

**Calculated Risk**: {risk}% — Level: {audit_data.risk_level.value}"""
        else:
            summary = f"""{status}

{doc_type} #{audit_data.document_number} بقيمة ﷼ {amount}.

رغم تحقيق نسبة امتثال {compliance}%، {'إلا أن' if audit_data.rules_failed > 0 else 'و'} 
{'المخالفات المكتشفة' if audit_data.rules_failed > 0 else 'الأداء الجيد'} 
{'تؤثر بشكل مباشر' if audit_data.rules_failed > 0 else 'يدعم'} على صلاحية الاعتماد.

**المخاطرة المحسوبة**: {risk}% — تصنيف {audit_data.risk_level.value}"""

        return summary

    def _generate_key_findings(self, audit_data: DocumentAuditData, language: str = "ar") -> str:
        """2 — Key Findings (3-5 bullet points)."""
        t = lambda ar, en: self._t(ar, en, language)
        findings = []
        total_rules = audit_data.rules_passed + audit_data.rules_failed

        if audit_data.compliance_score >= 90:
            findings.append(f"✅ **{t('نسبة امتثال عالية', 'High Compliance Rate')}**: {audit_data.compliance_score}%")

        if audit_data.rules_passed >= 8:
            findings.append(f"✅ **{t('قواعد ناجحة', 'Rules Passed')}**: {audit_data.rules_passed} {t('من', 'of')} {total_rules}")

        if audit_data.supplier_vat_valid:
            findings.append(f"✅ **{t('مورد موثوق', 'Trusted Supplier')}**: {audit_data.supplier_name} ({t('ضريبة سارية', 'Valid VAT')})")

        if audit_data.zatca_compliance == 100:
            findings.append(f"✅ **{t('امتثال ZATCA كامل', 'Full ZATCA Compliance')}**: {audit_data.zatca_compliance}%")

        if audit_data.rules_failed > 0:
            blocking = [r for r in audit_data.failed_rules if r.blocks_approval]
            rule_name = lambda r: r.name_en if language == "en" and r.name_en else r.name_ar
            if blocking:
                findings.append(
                    f"❌ **{t('مخالفات حرجة', 'Critical Violations')}**: "
                    f"{len(blocking)} {t('قاعدة تمنع الاعتماد', 'rule(s) blocking approval')}\n"
                    f"   • {chr(10).join([f'{r.code}: {rule_name(r)}' for r in blocking])}"
                )
            else:
                findings.append(
                    f"⚠️ **{t('مخالفات غير حرجة', 'Non-critical Violations')}**: "
                    f"{audit_data.rules_failed} {t('قاعدة لا تمنع الاعتماد', 'rule(s) — approval not blocked')}"
                )

        if audit_data.risk_score > 75:
            findings.append(f"🔴 **{t('مخاطرة مرتفعة', 'High Risk')}**: {t('درجة', 'Score')} {audit_data.risk_score}%")

        return "\n\n".join(findings)

    def _generate_risk_interpretation(self, audit_data: DocumentAuditData, language: str = "ar") -> str:
        """3 — Risk Interpretation."""
        t = lambda ar, en: self._t(ar, en, language)
        if not audit_data.failed_rules:
            return f"✅ **{t('لا توجد مخالفات', 'No Violations')}** — {t('جميع القواعد آمنة', 'All rules passed')}"

        interpretation = []
        rule_name = lambda r: (r.name_en if language == "en" and r.name_en else r.name_ar)
        impact = lambda r: (
            (r.impact_en if language == "en" and r.impact_en else r.impact_ar)
            or t('يؤثر على صلاحية اعتماد المستند', 'Affects the validity of document approval')
        )
        risk_type = lambda r: (
            t('رقابية', 'Control') if 'موافق' in r.code or 'توقيع' in r.code
            else t('مالية', 'Financial') if 'مبلغ' in r.code
            else t('قانونية', 'Legal')
        )

        for rule in audit_data.failed_rules[:3]:
            blocks_label = (
                f"⚠️ **{t('يمنع الاعتماد', 'Blocks Approval')}**"
                if rule.blocks_approval
                else f"✓ {t('لا يمنع الاعتماد', 'Does not block approval')}"
            )
            if language == "en":
                interpretation.append(f"""
**{rule.code}: {rule_name(rule)}**

Issue: {rule.reason}

Interpretation:
- **Severity**: {rule.severity}
- **Impact**: {impact(rule)}
- **Risk Type**: {risk_type(rule)}

{blocks_label}
""")
            else:
                interpretation.append(f"""
**{rule.code}: {rule_name(rule)}**

المشكلة: {rule.reason}

التفسير:
- **الخطورة**: تصنيف {rule.severity}
- **التأثير**: {impact(rule)}
- **نوع المخاطرة**: {risk_type(rule)}

{blocks_label}
""")

        return "\n".join(interpretation)

    def _generate_business_impact(self, audit_data: DocumentAuditData, language: str = "ar") -> str:
        """4 — Business Impact."""
        t = lambda ar, en: self._t(ar, en, language)
        doc_type_info = self.document_context[audit_data.document_type]
        amount = self._format_amount(audit_data.total_amount, language)
        has_critical = any(r.blocks_approval for r in audit_data.failed_rules)

        if language == "en":
            impact = f"""
**Financial Amount**: {amount}

**Impact Scenarios:**

| Scenario | Likelihood | Effect |
|----------|-----------|--------|
| Internal audit finds the issue | High | Compliance note |
| External auditor escalates | High | Qualified audit opinion |
| Regulatory audit | Medium | Fines / penalties |
| Error reoccurrence | High | Weak control culture |

**Business Impact:**
{doc_type_info.get('decision_impact', '')}

**Conclusion:**
"""
            if audit_data.total_amount > 1_000_000 and has_critical:
                impact += f"⚠️ High-value document ({amount}) with critical violations — explicit documented approvals required."
            else:
                impact += "Risks are manageable with appropriate control measures in place."
        else:
            impact = f"""
**المبلغ المالي**: ﷼ {amount}

**سيناريوهات التأثير:**

| السيناريو | الاحتمالية | الأثر |
|----------|-----------|------|
| مراجعة داخلية توجد الخلل | عالية | ملاحظة على الامتثال |
| مراجع خارجي يرفع القضية | مرتفعة | تقييد رأي المراجع |
| تدقيق من الجهات الحكومية | متوسطة | غرامات/مخالفات |
| تكرار الخطأ | عالية | ضعف الثقافة الرقابية |

**التأثير على الأعمال:**
{doc_type_info.get('decision_impact', '')}

**الخلاصة:**
"""
            if audit_data.total_amount > 1_000_000 and has_critical:
                impact += f"⚠️ المبلغ كبير جداً (﷼ {amount}) و وجود مخالفات حرجة يستدعي موافقات صريحة و موثقة."
            else:
                impact += "المخاطر محتملة لكن قابلة للإدارة مع اتخاذ إجراءات رقابية."

        return impact

    def _generate_decision(self, audit_data: DocumentAuditData, language: str = "ar") -> str:
        """5 — Final Decision."""
        t = lambda ar, en: self._t(ar, en, language)
        blocking_rules = [r for r in audit_data.failed_rules if r.blocks_approval]
        rule_name = lambda r: (r.name_en if language == "en" and r.name_en else r.name_ar)

        if blocking_rules:
            decision = t("❌ **مرفوض — في الوقت الحالي**", "❌ **Rejected — At This Time**")
            reason_header = t(
                "المخالفات الحرجة التالية تمنع الاعتماد:\n",
                "The following critical violations block approval:\n"
            )
            reason = reason_header + "".join(f"• {r.code}: {rule_name(r)}\n" for r in blocking_rules)
            doc_status = t("معطل حتى التصحيح", "On hold until corrected")
        elif audit_data.compliance_score < 70:
            decision = t("🔴 **مرفوض — يتطلب مراجعة شاملة**", "🔴 **Rejected — Requires Comprehensive Review**")
            reason = t(
                f"نسبة الامتثال منخفضة جداً ({audit_data.compliance_score}%)",
                f"Compliance rate is too low ({audit_data.compliance_score}%)"
            )
            doc_status = t("معطل حتى المراجعة الشاملة", "On hold pending comprehensive review")
        elif audit_data.compliance_score < 85:
            decision = t("⚠️ **مشروط — مع شروط**", "⚠️ **Conditional — With Conditions**")
            cond_header = t("يمكن الاعتماد مع مراقبة الجوانب التالية:\n", "Approval allowed with monitoring of the following:\n")
            reason = cond_header + "".join(f"• {rule_name(r)}\n" for r in audit_data.failed_rules)
            doc_status = t("معطل حتى تصحيح الملاحظات", "On hold until observations are resolved")
        else:
            decision = t("✅ **موافق — يمكن الاعتماد**", "✅ **Approved — Ready for Approval**")
            reason = t("جميع المتطلبات الأساسية متوفرة", "All essential requirements are met")
            doc_status = t("جاهز للاعتماد الفوري", "Ready for immediate approval")

        status_label = t("الحالة", "Status")
        reason_label = t("السبب", "Reason")
        return f"""
{decision}

**{reason_label}:**
{reason}

**{status_label}:**
{doc_status}"""

    def _generate_immediate_actions(self, audit_data: DocumentAuditData, language: str = "ar") -> str:
        """Immediate Actions."""
        t = lambda ar, en: self._t(ar, en, language)
        rule_name = lambda r: (r.name_en if language == "en" and r.name_en else r.name_ar)

        if not audit_data.failed_rules:
            return f"✅ {t('لا توجد إجراءات فورية — المستند جاهز', 'No immediate actions required — document is ready')}"

        header = t("**إجراءات فورية (في الساعات القادمة):**", "**Immediate Actions (within the next few hours):**")
        action_label = t("إجراء", "Action")
        deadline_label = t("موعد", "Deadline")
        actions = [header + "\n"]

        for idx, rule in enumerate(audit_data.failed_rules[:3], 1):
            if rule.blocks_approval:
                actions.append(f"{idx}. **{rule_name(rule)}**")
                actions.append(f"   - {action_label}: {self._get_action_for_rule(rule, language)}")
                actions.append(f"   - {deadline_label}: {self._get_deadline_for_rule(rule, language)}\n")

        return "\n".join(actions)

    def _generate_process_improvements(self, audit_data: DocumentAuditData, language: str = "ar") -> str:
        """Process Improvements."""
        t = lambda ar, en: self._t(ar, en, language)
        doc_type = audit_data.document_type.value
        header = t("**تحسينات العملية (مستقبلاً):**", "**Process Improvements (Going Forward):**")
        improvements = [header + "\n"]

        if doc_type == "purchase_order":
            improvements.extend([
                f"1. **{t('تحديث نموذج أمر الشراء', 'Update Purchase Order Form')}**",
                "   - " + t("إضافة حقل إلزامي: 'موافق من'", "Add mandatory field: 'Approved By'"),
                f"   - {t('النظام يرفض أي طلب بدون موافقة', 'System rejects any request without approval')}\n",
                f"2. **{t('توضيح سلسلة الموافقات', 'Clarify Approval Chain')}**",
                "   - " + t("من يوافق على الطلبات < 1 مليون؟", "Who approves requests < 1M?"),
                "   - " + t("من يوافق على الطلبات 1-5 مليون؟", "Who approves 1M-5M?"),
                f"   - {t('من يوافق على الطلبات > 5 مليون؟', 'Who approves > 5M?')}\n",
                f"3. **{t('تدريب المستخدمين', 'User Training')}**",
                "   - " + t("الموافقة ليست اختيارية", "Approval is not optional"),
                f"   - {t('يجب إكمالها قبل الإرسال', 'Must be completed before submission')}",
            ])
        elif doc_type == "invoice":
            improvements.extend([
                f"1. **{t('تحديث نموذج الفاتورة', 'Update Invoice Form')}**",
                "   - " + t("إضافة تحقق آلي من QR ZATCA", "Add automatic ZATCA QR verification"),
                f"   - {t('التحقق من مطابقة الضريبة تلقائياً', 'Auto-verify tax calculations')}\n",
                f"2. **{t('تفعيل التنبيهات', 'Enable Alerts')}**",
                "   - " + t("تنبيه فوري عند كشف فاتورة مكررة", "Instant alert on duplicate invoice detection"),
                f"   - {t('تنبيه عند انحراف الأسعار', 'Alert on price deviation')}\n",
                f"3. **{t('تحسين البيانات الأساسية', 'Improve Master Data')}**",
                "   - " + t("التحقق من بيانات المورد قبل الإدخال", "Validate supplier data before entry"),
                f"   - {t('منع إدخال مورد بدون ضريبة سارية', 'Block supplier entry without valid VAT')}",
            ])
        elif doc_type == "bank_statement":
            improvements.extend([
                f"1. **{t('تفعيل المطابقة الآلية', 'Enable Automated Reconciliation')}**",
                "   - " + t("ربط تلقائي مع كشوفات البنك", "Automatic bank statement linkage"),
                f"   - {t('تنبيهات فورية عند الاختلافات', 'Instant alerts on discrepancies')}\n",
                f"2. **{t('رصد المعاملات المريبة', 'Monitor Suspicious Transactions')}**",
                "   - " + t("تنبيهات AML (مكافحة تبييض الأموال)", "AML alerts (Anti-Money Laundering)"),
                f"   - {t('رصد العتبات المشبوهة', 'Monitor suspicious thresholds')}\n",
                f"3. **{t('توثيق أفضل', 'Improved Documentation')}**",
                "   - " + t("قوائم مطابقات يومية", "Daily reconciliation lists"),
                f"   - {t('توثيق التسويات اليدوية', 'Document manual adjustments')}",
            ])

        return "\n".join(improvements)

    def _generate_ai_insight(self, audit_data: DocumentAuditData, language: str = "ar") -> str:
        """AI Insight — isolated vs. systemic problem."""
        t = lambda ar, en: self._t(ar, en, language)
        insight = f"**{t('التحليل الذكي', 'AI Analysis')}:**\n\n"

        if not audit_data.failed_rules:
            insight += f"✅ **{t('نمط صحي', 'Healthy Pattern')}** — {t('لا توجد مشاكل متكررة', 'No recurring issues')}"
        else:
            rule_codes = set(r.code[:3] for r in audit_data.failed_rules)
            if len(rule_codes) == 1:
                insight += f"🔴 **{t('مشكلة نظامية', 'Systemic Issue')}** — {t('نفس المشكلة تتكرر', 'Same problem recurring')}"
                insight += f"\n- {t('العامل', 'Factor')}: {list(rule_codes)[0]}"
                insight += f"\n- {t('الحل', 'Recommendation')}: {t('إعادة بناء العملية من الصفر', 'Rebuild the process from scratch')}"
            else:
                insight += f"⚠️ **{t('مشاكل متعددة', 'Multiple Issues')}** — {t('عدة نقاط ضعف', 'Several weak points')}"
                insight += f"\n- {t('عدد المناطق المتأثرة', 'Affected areas')}: {len(rule_codes)}"

        insight += f"\n\n**{t('الخلاصة المبدئية', 'Preliminary Conclusion')}:**\n"

        if audit_data.risk_score > 80:
            insight += t(
                "⚠️ درجة المخاطرة المرتفعة تشير إلى **مشاكل هيكلية** في العملية",
                "⚠️ The elevated risk score indicates **structural issues** in the process"
            )
        elif audit_data.compliance_score < 80:
            insight += t(
                "📌 نسبة الامتثال المنخفضة تستدعي **تدريب محسّن** للمستخدمين",
                "📌 The low compliance rate calls for **improved user training**"
            )
        else:
            insight += t(
                "✅ الأداء جيد — تركيز على الجوانب المتبقية فقط",
                "✅ Performance is good — focus on the remaining minor issues only"
            )

        return insight

    # ========== Helper Methods ==========

    def _format_amount(self, amount: float, language: str = "ar") -> str:
        """Format monetary amounts with language-aware number words."""
        if language == "en":
            if amount >= 1_000_000:
                return f"{amount / 1_000_000:.1f}M SAR"
            elif amount >= 1_000:
                return f"{amount / 1_000:.1f}K SAR"
            return f"SAR {amount:.2f}"
        else:
            if amount >= 1_000_000:
                return f"{amount / 1_000_000:.1f} مليون"
            elif amount >= 1_000:
                return f"{amount / 1_000:.1f} ألف"
            return f"{amount:.2f}"

    def _get_action_for_rule(self, rule: FailedRule, language: str = "ar") -> str:
        """Recommended action per rule (bilingual)."""
        actions_ar = {
            "PO-008": "الحصول على موافقة من السلطة المختصة",
            "INV-005": "التحقق من بيانات المورد وضريبته",
            "INV-007": "التحقق من عدم التكرار وإعادة الإرسال",
            "VAT-003": "فحص حساب الضريبة وتصحيحه",
            "QR-001": "إعادة توليد QR من النظام",
            "BNK-002": "مطابقة يدوية مع البنك",
        }
        actions_en = {
            "PO-008": "Obtain approval from the competent authority",
            "INV-005": "Verify supplier data and VAT registration",
            "INV-007": "Confirm no duplicate and resubmit",
            "VAT-003": "Review and correct the tax calculation",
            "QR-001": "Regenerate QR code from the system",
            "BNK-002": "Perform manual bank reconciliation",
        }
        if language == "en":
            return actions_en.get(rule.code, f"Correct: {rule.reason}")
        return actions_ar.get(rule.code, f"تصحيح: {rule.reason}")

    def _get_deadline_for_rule(self, rule: FailedRule, language: str = "ar") -> str:
        """Deadline per rule (bilingual)."""
        t = lambda ar, en: self._t(ar, en, language)
        if rule.severity == "Critical":
            return t("فوري (اليوم)", "Immediate (today)")
        elif rule.severity == "High":
            return t("24 ساعة", "24 hours")
        return t("48 ساعة", "48 hours")


# ========== Utility Functions ==========

def create_audit_data_from_dict(data: Dict) -> DocumentAuditData:
    """
    تحويل قاموس البيانات إلى DocumentAuditData
    """
    failed_rules = [
        FailedRule(
            code=r.get("code"),
            name_ar=r.get("name_ar", r.get("name")),
            name_en=r.get("name_en"),
            reason=r.get("reason"),
            severity=r.get("severity", "Medium"),
            blocks_approval=r.get("blocks_approval", False),
            impact_ar=r.get("impact_ar"),
            impact_en=r.get("impact_en")
        )
        for r in data.get("failed_rules", [])
    ]

    return DocumentAuditData(
        document_type=DocumentType(data.get("document_type")),
        document_id=data.get("document_id", ""),
        document_number=data.get("document_number", ""),
        company=data.get("company", ""),
        total_amount=data.get("total_amount", 0),
        currency=data.get("currency", "SAR"),
        compliance_score=data.get("compliance_score", 0),
        risk_score=data.get("risk_score", 0),
        risk_level=RiskLevel(data.get("risk_level", "low")),
        rules_passed=data.get("rules_passed", 0),
        rules_failed=data.get("rules_failed", 0),
        failed_rules=failed_rules,
        supplier_name=data.get("supplier", {}).get("name"),
        supplier_vat_valid=data.get("supplier", {}).get("vat_valid"),
        zatca_compliance=data.get("zatca_compliance"),
        audit_date=data.get("audit_date", datetime.now()),
        auditor_name=data.get("auditor_name", "AI Audit System"),
        custom_fields=data.get("custom_fields", {})
    )
