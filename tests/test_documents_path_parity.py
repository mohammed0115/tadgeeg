"""بوابة الخطوة ٤ — تبديل مسار المستندات. **وهي ساقطة اليوم.**

الخطوة ٤ تريد سطرًا واحدًا في `core/services/pipeline.py:203`: استبدال
`AuditEngine` بـ`LegacyAuditEngineAdapter`، فينتقل المسار من 18 قاعدة إلى 131.

القياس على 34 مستندًا حقيقيًا من 22 نوعًا (جهاز تطوير · قراءة-فقط · عدّاد
`AuditRun` قبل وبعد متساويان) أعطى شرطين حاجبين، وكلاهما مُثبَّت هنا:

  ١. الجسر يرفض شكل الاستدعاء الذي يستعمله مسار المستندات.
     `pipeline.py:223` ينادي `evaluate(document=..., context=...)` بلا
     `invoice_id`، و`evaluate` أوّل ما تفعله أن ترفع `ValueError` بدونه.
     34 من 34.

  ٢. مسار المستندات مكسور **قبل** الشحنة: المحرّك القديم يُنتج تقريرًا
     بـ18 قاعدة، ثم `_serialise_audit_report` يرفع `AttributeError` لأنه
     يقرأ `passed_count` و`AuditReport` يسمّيها `passed_rules`.
     34 من 34. والاستثناء يبتلعه `except Exception` في المرحلة ٣، فيبقى
     `summary["audit"]` فارغًا بلا أثر مرئي.

🔴 **الاختبارات أدناه تُثبّت عطلين حيّين، لا سلوكًا مرغوبًا.**
   نجاحها يعني «العطل ما زال كما قِيس»؛ وسقوطها يعني أن أحدهما تحرّك —
   وحينها تُعاد البوابة قبل أي تبديل، لا يُعدَّل الاختبار.

المرجع الذهبي لا يحرس هذه الشحنة: مولّده ينادي المحرّك مباشرةً متجاوزًا
التوجيه، فيقيس ما يحكم به الأنبوب لا أيّ أنبوب يُستدعى. البصمة تبقى مطابقة
سواء نجح التبديل أو كسر المسار. هذا الملف هو الحارس البديل.
"""

import inspect
import uuid

import pytest


# ═════════════════════════════════════════════════════════════════════════════
# ١. الشرط الحاجب الأول — الجسر يرفض شكل استدعاء مسار المستندات
# ═════════════════════════════════════════════════════════════════════════════

def test_the_documents_path_calls_evaluate_without_invoice_id():
    """موضع الاستدعاء يُقرأ من المصدر لا يُكتب بيدي.

    لو مرّر أحدهم `invoice_id` لاحقًا، هذا الاختبار يسقط — وهو الوقت الذي
    تُعاد فيه البوابة.
    """
    import core.services.pipeline as pipeline_module

    source = inspect.getsource(pipeline_module.run_full_pipeline_for_file)
    call_start = source.index("audit_engine.evaluate(")
    call = source[call_start:source.index(")", call_start)]

    assert "invoice_id" not in call, (
        "مسار المستندات صار يمرّر invoice_id — الشرط الحاجب الأول تغيّر.\n"
        f"الاستدعاء الآن: {call!r}\n"
        "أعِد قياس البوابة قبل التبديل."
    )


def test_the_adapter_requires_invoice_id_and_so_refuses_that_call():
    """الجسر يرفع ValueError قبل أن يصل إلى أي منطق خاص بالمستند.

    الرفض غير مشروط بالبيانات: هو أوّل سطر في `evaluate`. لذلك النتيجة
    34/34 في القياس ليست خاصيّة عيّنة.
    """
    from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
        LegacyAuditEngineAdapter,
    )

    adapter = LegacyAuditEngineAdapter(organization_id=uuid.uuid4())

    with pytest.raises(ValueError, match="requires invoice_id"):
        adapter.evaluate(document={"total_amount": 100}, context={})


def test_the_adapter_hardcodes_sales_invoice_as_the_document_type():
    """وحتى مع invoice_id، الجسر يثبّت النوع على sales_invoice.

    مسار المستندات يحمل 22 نوعًا مخزَّنًا، والمرحلة ٢ تصنّفها إلى
    invoice / other / bank_statement / payroll / receipt. لا واحد منها
    sales_invoice. والمعرّف الذي يملكه المسار هو مفتاح `Document`، لا مفتاح
    السجل المطبوع — وهو تعارض فضاءات المعرّفات نفسه الذي عولج في المرحلة ١ب.
    """
    from apps.rule_engine.services.compatibility import legacy_audit_adapter

    source = inspect.getsource(
        legacy_audit_adapter.LegacyAuditEngineAdapter.evaluate)

    assert 'document_type="sales_invoice"' in source, (
        "الجسر لم يعد يثبّت sales_invoice — الشرط الحاجب الثاني تغيّر، "
        "أعِد قياس البوابة."
    )


# ═════════════════════════════════════════════════════════════════════════════
# ٢. الشرط الحاجب الثاني — المسار مكسور قبل الشحنة
# ═════════════════════════════════════════════════════════════════════════════

_SERIALISER_READS = (
    "risk_score", "risk_level", "total_rules", "passed_count", "failed_count",
    "skipped_count", "error_count", "escalate", "processing_time_ms",
    "summary", "rule_results",
)


def test_the_names_the_serialiser_reads_are_read_from_the_serialiser():
    """القائمة أعلاه ليست ذاكرتي — تُقارَن بما يقرأه المُسلسِل فعلًا."""
    import core.services.pipeline as pipeline_module

    source = inspect.getsource(pipeline_module._serialise_audit_report)
    actual = {
        name for name in _SERIALISER_READS if f"report.{name}" in source
    }
    assert actual == set(_SERIALISER_READS), (
        "المُسلسِل تغيّرت الحقول التي يقرأها.\n"
        f"مفقود من المصدر: {sorted(set(_SERIALISER_READS) - actual)}"
    )


def test_the_old_report_is_missing_four_of_the_names_the_serialiser_reads():
    """`AuditReport` يسمّيها `*_rules`، والمُسلسِل يقرأ `*_count`.

    هذا عطل حيّ، لا سلوك مرغوب. سقوط هذا الاختبار يعني أن أحدهم أضاف
    الأسماء البديلة — وهو الإصلاح الصحيح — فيُقلَب الاختبار حينها.
    """
    from apps.audit.audit_engine import AuditReport

    report = AuditReport()
    missing = [n for n in _SERIALISER_READS if not hasattr(report, n)]

    assert missing == ["passed_count", "failed_count",
                       "skipped_count", "error_count"], (
        f"الحقول الناقصة تغيّرت: {missing}. "
        "إن صارت فارغة فقد أُصلح العطل — اقلِب هذا الاختبار."
    )


def test_serialising_an_old_report_raises_and_the_pipeline_swallows_it():
    """المرحلة ٣ تلتقط كل استثناء، فالعطل بلا أثر مرئي.

    يُشغَّل المُسلسِل الحقيقي على تقرير حقيقي — لا محاكاة: كائن مُقلَّد يجيب
    عن أي اسم، فيجعل عطل الاسم غير مرئي تمامًا كما يجعله `getattr`.
    """
    from apps.audit.audit_engine import AuditReport
    from core.services.pipeline import _serialise_audit_report

    with pytest.raises(AttributeError, match="passed_count"):
        _serialise_audit_report(AuditReport(total_rules=18, passed_rules=6))


# ═════════════════════════════════════════════════════════════════════════════
# ٣. النصف الموجب — الجسر يُرضي المُسلسِل الذي لا يُرضيه المحرّك القديم
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_the_adapter_result_does_satisfy_the_serialiser():
    """`AuditRunResult` يحمل الحقول السبعة التي أُضيفت في الشحنة ١.

    فالتبديل — لو أمكن — يُصلح العطل الثاني بلا سطر إضافي. وهذا وحده لا
    يجعله جائزًا: الشرط الأول ما زال حاجبًا.
    """
    from apps.authentication.models import Organization
    from apps.rule_engine.models import AuditRun
    from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
        AuditRunResult,
    )
    from core.services.pipeline import _serialise_audit_report

    org = Organization.objects.create(name="Parity Org", name_ar="تكافؤ")
    run = AuditRun.objects.create(
        organization=org,
        document_type="purchase_order",
        document_id=uuid.uuid4(),
        total_rules=131, passed_rules=120, failed_rules=8,
        warning_rules=2, skipped_rules=1, error_rules=0,
        risk_score=42, risk_level="medium",
    )

    payload = _serialise_audit_report(AuditRunResult.from_audit_run(run))

    assert payload["total_rules"] == 131
    assert payload["passed_count"] == 120
    assert payload["failed_count"] == 8
    assert payload["skipped_count"] == 1
    assert payload["error_count"] == 0
    assert payload["rule_results"] == []


# ═════════════════════════════════════════════════════════════════════════════
# ٤. الحارس يُرى وهو يفشل
# ═════════════════════════════════════════════════════════════════════════════

def test_this_guard_can_fail():
    """لو مُنح الجسر `invoice_id`، لا يعود يرفع ValueError.

    زرع مخالف حقيقي: نفس الجسر، ونفس الاستدعاء، ويختلف وسيط واحد. فإن مرّ
    هذا دون فرق، فاختبار الرفض أعلاه لا يقيس الرفض.
    """
    from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
        LegacyAuditEngineAdapter,
    )

    adapter = LegacyAuditEngineAdapter(organization_id=uuid.uuid4())

    with pytest.raises(ValueError, match="requires invoice_id"):
        adapter.evaluate(document={}, context={})

    # ومع invoice_id يمضي إلى ما بعد الحارس — فيفشل لسبب آخر، لا لغيابه.
    with pytest.raises(Exception) as caught:
        adapter.evaluate(document={}, invoice_id=uuid.uuid4(), context={})

    assert "requires invoice_id" not in str(caught.value), (
        "الجسر ما زال يشكو من invoice_id رغم تمريره — "
        "فاختبار الرفض أعلاه لا يقيس ما يدّعيه"
    )
