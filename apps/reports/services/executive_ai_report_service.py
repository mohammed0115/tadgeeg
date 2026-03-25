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
    currency: str = "SAR"
    compliance_score: int  # 0-100
    risk_score: float  # 0-100
    risk_level: RiskLevel
    rules_passed: int
    rules_failed: int
    failed_rules: List[FailedRule]
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

    def generate_report(self, audit_data: DocumentAuditData) -> Dict[str, str]:
        """
        توليد التقرير التنفيذي الكامل
        Returns: dict with all report sections
        """
        return {
            "executive_summary": self._generate_executive_summary(audit_data),
            "key_findings": self._generate_key_findings(audit_data),
            "risk_interpretation": self._generate_risk_interpretation(audit_data),
            "business_impact": self._generate_business_impact(audit_data),
            "decision": self._generate_decision(audit_data),
            "immediate_actions": self._generate_immediate_actions(audit_data),
            "process_improvements": self._generate_process_improvements(audit_data),
            "ai_insight": self._generate_ai_insight(audit_data)
        }

    def _generate_executive_summary(self, audit_data: DocumentAuditData) -> str:
        """
        1️⃣ الملخص التنفيذي
        فقرة قصيرة تجيب على: ما الوضع؟ هل آمن؟ هل توجد مخاطر؟
        """
        doc_type = self.document_context[audit_data.document_type]["ar"]
        compliance = audit_data.compliance_score
        risk = audit_data.risk_score

        # تحديد الحالة
        if audit_data.rules_failed == 0 and compliance >= 95:
            status = f"✅ **ممتاز** — يمكن الاعتماد الفوري"
            tone = "إيجابي جداً"
        elif audit_data.rules_failed > 0 and any(r.blocks_approval for r in audit_data.failed_rules):
            status = f"❌ **مرفوض** — يتطلب تصحيح فوري"
            tone = "حرج"
        elif compliance >= 85:
            status = f"⚠️ **مشروط** — يمكن الاعتماد مع مراقبة"
            tone = "تحفظ"
        else:
            status = f"🔴 **ضعيف** — يتطلب مراجعة شاملة"
            tone = "سلبي"

        summary = f"""{status}

{doc_type} #{audit_data.document_number} بقيمة ﷼ {self._format_amount(audit_data.total_amount)}.

رغم تحقيق نسبة امتثال {compliance}%، {'إلا أن' if audit_data.rules_failed > 0 else 'و'} 
{'المخالفات المكتشفة' if audit_data.rules_failed > 0 else 'الأداء الجيد'} 
{'تؤثر بشكل مباشر' if audit_data.rules_failed > 0 else 'يدعم'} على صلاحية الاعتماد.

**المخاطرة المحسوبة**: {risk}% — تصنيف {audit_data.risk_level.value}"""

        return summary

    def _generate_key_findings(self, audit_data: DocumentAuditData) -> str:
        """
        2️⃣ أهم النتائج (3-5 نقاط)
        """
        findings = []

        # نقاط القوة
        if audit_data.compliance_score >= 90:
            findings.append(f"✅ **نسبة امتثال عالية**: {audit_data.compliance_score}%")

        if audit_data.rules_passed >= 8:
            findings.append(f"✅ **قواعس ناجحة**: {audit_data.rules_passed} من {audit_data.rules_passed + audit_data.rules_failed}")

        if audit_data.supplier_vat_valid:
            findings.append(f"✅ **مورد موثوق**: {audit_data.supplier_name} (ضريبة سارية)")

        if audit_data.zatca_compliance == 100:
            findings.append(f"✅ **امتثال ZATCA كامل**: {audit_data.zatca_compliance}%")

        # نقاط الضعف
        if audit_data.rules_failed > 0:
            blocking = [r for r in audit_data.failed_rules if r.blocks_approval]
            if blocking:
                findings.append(
                    f"❌ **مخالفات حرجة**: {len(blocking)} قاعدة تمنع الاعتماد\n"
                    f"   • {chr(10).join([f'{r.code}: {r.name_ar}' for r in blocking])}"
                )
            else:
                findings.append(
                    f"⚠️ **مخالفات غير حرجة**: {audit_data.rules_failed} قاعدة لا تمنع الاعتماد"
                )

        if audit_data.risk_score > 75:
            findings.append(f"🔴 **مخاطرة مرتفعة**: درجة {audit_data.risk_score}%")

        return "\n\n".join(findings)

    def _generate_risk_interpretation(self, audit_data: DocumentAuditData) -> str:
        """
        3️⃣ تفسير المخاطر
        لماذا خطير؟ لماذا يؤثر على القرار؟
        """
        if not audit_data.failed_rules:
            return "✅ **لا توجد مخالفات** — جميع القواعس آمنة"

        interpretation = []

        for rule in audit_data.failed_rules[:3]:  # أهم 3 مخالفات
            interpretation.append(f"""
**{rule.code}: {rule.name_ar}**

المشكلة: {rule.reason}

التفسير:
- **الخطورة**: تصنيف {rule.severity}
- **التأثير**: {rule.impact_ar or 'يؤثر على صلاحية اعتماد المستند'}
- **نوع المخاطرة**: {'رقابية' if 'موافق' in rule.code or 'توقيع' in rule.code else 'مالية' if 'مبلغ' in rule.code else 'قانونية'}

{'⚠️ **يمنع الاعتماد**' if rule.blocks_approval else '✓ لا يمنع الاعتماد'}
""")

        return "\n".join(interpretation)

    def _generate_business_impact(self, audit_data: DocumentAuditData) -> str:
        """
        4️⃣ تأثير الأعمال
        ماذا يحدث إذا اعتمدنا؟ ما المخاطر؟
        """
        doc_type_info = self.document_context[audit_data.document_type]

        impact = f"""
**المبلغ المالي**: ﷼ {self._format_amount(audit_data.total_amount)}

**سيناريوهات التأثير:**

| السيناريو | الاحتمالية | الأثر |
|----------|-----------|------|
| مراجعة داخلية توجد الخلل | عالية | ملاحظة على الامتثال |
| مراجع خارجي يرفع القضية | مرتفعة | تقييد رأي المراجع |
| تدقيق من الجهات الحكومية | متوسطة | غرامات/مخالفات |
| تكرار الخطأ | عالية | ضعف الثقافة الرقابية |

**التأثير على الأعمال:**
{doc_type_info['decision_impact']}

**الخلاصة:**
"""
        # إضافة تحذير إذا كان المبلغ كبيراً والمخالفات حرجة
        if audit_data.total_amount > 1_000_000 and any(r.blocks_approval for r in audit_data.failed_rules):
            impact += f"⚠️ المبلغ كبير جداً (﷼ {self._format_amount(audit_data.total_amount)}) "
            impact += "و وجود مخالفات حرجة يستدعي موافقات صريحة و موثقة."
        else:
            impact += "المخاطر محتملة لكن قابلة للإدارة مع اتخاذ إجراءات رقابية."

        return impact

    def _generate_decision(self, audit_data: DocumentAuditData) -> str:
        """
        5️⃣ القرار النهائي
        """
        # تحديد القرار
        blocking_rules = [r for r in audit_data.failed_rules if r.blocks_approval]

        if blocking_rules:
            decision = "❌ **مرفوض — في الوقت الحالي**"
            reason = f"المخالفات الحرجة التالية تمنع الاعتماد:\n"
            for rule in blocking_rules:
                reason += f"• {rule.code}: {rule.name_ar}\n"
        elif audit_data.compliance_score < 70:
            decision = "🔴 **مرفوض — يتطلب مراجعة شاملة**"
            reason = f"نسبة الامتثال منخفضة جداً ({audit_data.compliance_score}%)"
        elif audit_data.compliance_score < 85:
            decision = "⚠️ **مشروط — مع شروط**"
            reason = f"يمكن الاعتماد مع مراقبة الجوانب التالية:\n"
            for rule in audit_data.failed_rules:
                reason += f"• {rule.name_ar}\n"
        else:
            decision = "✅ **موافق — يمكن الاعتماد**"
            reason = f"جميع المتطلبات الأساسية متوفرة"

        return f"""
{decision}

**السبب:**
{reason}

**الحالة:**
المستند {'معطل حتى التصحيح' if 'مرفوض' in decision else 'معطل حتى تصحيح الملاحظات' if 'شروط' in decision else 'جاهز للاعتماد الفوري'}"""

    def _generate_immediate_actions(self, audit_data: DocumentAuditData) -> str:
        """
        📋 إجراءات فورية
        """
        if not audit_data.failed_rules:
            return "✅ لا توجد إجراءات فورية — المستند جاهز"

        actions = ["**إجراءات فورية (في الساعات القادمة):**\n"]

        for idx, rule in enumerate(audit_data.failed_rules[:3], 1):
            if rule.blocks_approval:
                actions.append(f"{idx}. **{rule.name_ar}**")
                actions.append(f"   - إجراء: {self._get_action_for_rule(rule)}")
                actions.append(f"   - موعد: {self._get_deadline_for_rule(rule)}\n")

        return "\n".join(actions)

    def _generate_process_improvements(self, audit_data: DocumentAuditData) -> str:
        """
        📋 تحسينات العملية
        """
        improvements = ["**تحسينات العملية (مستقبلاً):**\n"]

        doc_type = audit_data.document_type.value

        if doc_type == "purchase_order":
            improvements.extend([
                "1. **تحديث نموذج أمر الشراء**",
                "   - إضافة حقل إلزامي: 'موافق من'",
                "   - النظام يرفض أي طلب بدون موافقة\n",
                "2. **توضيح سلسلة الموافقات**",
                "   - من يوافق على الطلبات < 1 مليون؟",
                "   - من يوافق على الطلبات 1-5 مليون؟",
                "   - من يوافق على الطلبات > 5 مليون؟\n",
                "3. **تدريب المستخدمين**",
                "   - الموافقة ليست اختيارية",
                "   - يجب إكمالها قبل الإرسال"
            ])
        elif doc_type == "invoice":
            improvements.extend([
                "1. **تحديث نموذج الفاتورة**",
                "   - إضافة تحقق آلي من QR ZATCA",
                "   - التحقق من مطابقة الضريبة تلقائياً\n",
                "2. **تفعيل التنبيهات**",
                "   - تنبيه فوري عند كشف فاتورة مكررة",
                "   - تنبيه عند انحراف الأسعار\n",
                "3. **تحسين البيانات الأساسية**",
                "   - التحقق من بيانات المورد قبل الإدخال",
                "   - منع إدخال مورد بدون ضريبة سارية"
            ])
        elif doc_type == "bank_statement":
            improvements.extend([
                "1. **تفعيل المطابقة الآلية**",
                "   - ربط تلقائي مع كشوفات البنك",
                "   - تنبيهات فوري عند الاختلافات\n",
                "2. **رصد المعاملات المريبة**",
                "   - تنبيهات AML (مكافحة تبييض الأموال)",
                "   - رصد العتبات المشبوهة\n",
                "3. **توثيق أفضل**",
                "   - قوائم مطابقات يومية",
                "   - توثيق التسويات اليدوية"
            ])

        return "\n".join(improvements)

    def _generate_ai_insight(self, audit_data: DocumentAuditData) -> str:
        """
        💡 الرؤية الذكية
        هل المشكلة معزولة أم نظامية؟
        """
        insight = "**التحليل الذكي:**\n\n"

        # تحليل نمط المشاكل
        if not audit_data.failed_rules:
            insight += "✅ **نمط صحي** — لا توجد مشاكل متكررة"
        else:
            rule_codes = set(r.code[:3] for r in audit_data.failed_rules)
            if len(rule_codes) == 1:
                insight += "🔴 **مشكلة نظامية** — نفس المشكلة تتكرر"
                insight += f"\n- العامل: {list(rule_codes)[0]}"
                insight += "\n- الحل: إعادة بناء العملية من الصفر"
            else:
                insight += "⚠️ **مشاكل متعددة** — عدة نقاط ضعف"
                insight += f"\n- عدد المناطق المتأثرة: {len(rule_codes)}"

        insight += "\n\n**الخلاصة المبدئية:**\n"

        if audit_data.risk_score > 80:
            insight += "⚠️ درجة المخاطرة المرتفعة تشير إلى **مشاكل هيكلية** في العملية"
        elif audit_data.compliance_score < 80:
            insight += "📌 نسبة الامتثال المنخفضة تستدعي **تدريب محسّن** للمستخدمين"
        else:
            insight += "✅ الأداء جيد — تركيز على الجوانب المتبقية فقط"

        return insight

    # ========== Helper Methods ==========

    def _format_amount(self, amount: float) -> str:
        """تنسيق المبالغ المالية"""
        if amount >= 1_000_000:
            return f"{amount / 1_000_000:.1f} مليون"
        elif amount >= 1_000:
            return f"{amount / 1_000:.1f} ألف"
        return f"{amount:.2f}"

    def _get_action_for_rule(self, rule: FailedRule) -> str:
        """الإجراء الموصى به لكل قاعدة"""
        actions = {
            "PO-008": "الحصول على موافقة من السلطة المختصة",
            "INV-005": "التحقق من بيانات المورد وضريبته",
            "INV-007": "التحقق من عدم التكرار وإعادة الإرسال",
            "VAT-003": "فحص حساب الضريبة وتصحيحه",
            "QR-001": "إعادة توليد QR من النظام",
            "BNK-002": "مطابقة يدوية مع البنك",
        }
        return actions.get(rule.code, f"تصحيح: {rule.reason}")

    def _get_deadline_for_rule(self, rule: FailedRule) -> str:
        """الموعد النهائي لكل إجراء"""
        if rule.severity == "Critical":
            return "فوري (اليوم)"
        elif rule.severity == "High":
            return "24 ساعة"
        else:
            return "48 ساعة"


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
        auditor_name=data.get("auditor_name", "نظام التدقيق الذكي"),
        custom_fields=data.get("custom_fields", {})
    )
