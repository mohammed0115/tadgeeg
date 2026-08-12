"""بوابة الخطوة ٤ — تبديل مسار المستندات. **وهي ساقطة اليوم.**

الخطوة ٤ تريد سطرًا واحدًا في `core/services/pipeline.py:203`: استبدال
`AuditEngine` بـ`LegacyAuditEngineAdapter`، فينتقل المسار من 18 قاعدة إلى 131.

القياس على 34 مستندًا حقيقيًا من 22 نوعًا (جهاز تطوير · قراءة-فقط · عدّاد
`AuditRun` قبل وبعد متساويان) أعطى شرطين حاجبين، وكلاهما مُثبَّت هنا:

  ١. الجسر يرفض شكل الاستدعاء الذي يستعمله مسار المستندات.
     `pipeline.py:223` ينادي `evaluate(document=..., context=...)` بلا
     `invoice_id`، و`evaluate` أوّل ما تفعله أن ترفع `ValueError` بدونه.
     34 من 34.

  ٢. ✅ **أُصلح في المرحلة ٥-٠.** مسار المستندات كان مكسورًا **قبل**
     الشحنة: المحرّك يُنتج تقريرًا بـ18 قاعدة، ثم `_serialise_audit_report`
     يرفع `AttributeError` لأنه يقرأ `passed_count` و`AuditReport` يسمّيها
     `passed_rules`. 34 من 34. والاستثناء يبتلعه `except Exception` في
     المرحلة ٣، فيبقى `summary["audit"]` فارغًا بلا أثر مرئي — ويسقط معه
     تصعيد الخطورة، لأن أسطره تقع بعد سطر المُسلسِل.

     الإصلاح: أربعة أسماء بديلة كـ`@property` في `AuditReport`. والاختبارات
     صارت تُثبّت الإصلاح لا العطل.

🔴 **الشرط الأول ما زال حاجبًا، واختباراته تُثبّت عطلًا حيًّا لا سلوكًا
   مرغوبًا.** نجاحها يعني «العطل ما زال كما قِيس»؛ وسقوطها يعني أنه تحرّك —
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

def _names_the_serialiser_reads() -> set[str]:
    """الأسماء التي يقرؤها `_serialise_audit_report` من كائن التقرير.

    تُستخرَج بالـ`ast` من المصدر، ولا تُكتب هنا. القائمة اليدوية هي جذر كل
    عيب في هذا المستودع، ولها هنا سبب إضافي: الاستثناء يقع عند أوّل اسم
    ناقص، فالعين تتوقّف عند `passed_count` ويختبئ خلفه اسم ثانٍ عشر.
    """
    import ast
    import textwrap

    import core.services.pipeline as pipeline_module

    tree = ast.parse(textwrap.dedent(
        inspect.getsource(pipeline_module._serialise_audit_report)))
    return {
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "report"
    }


def test_the_extraction_finds_the_names_it_is_supposed_to_find():
    """الأداة تُثبَت قبل أن يُنشَر رقم منها.

    أربع أدوات قياس في هذا المستودع أعطت أرقامًا واثقة عن سؤال آخر. فهذه
    تُقاس بأسماء يقينية: `risk_score` يُقرأ فعلًا، و`passed_rules` لا يُقرأ
    (هو الاسم الذي *لا* يستعمله المُسلسِل — وهو سبب العطل كلّه).
    """
    names = _names_the_serialiser_reads()

    assert "risk_score" in names
    assert "passed_count" in names
    assert "passed_rules" not in names, (
        "المُسلسِل صار يقرأ passed_rules — العقد تغيّر، أعِد قراءة الشحنة"
    )
    assert len(names) >= 11, f"الاستخراج أعاد {len(names)} اسمًا فقط: {sorted(names)}"


def test_the_report_satisfies_every_field_the_serialiser_reads():
    """`AuditReport` يعرض الأحد عشر كلها — وأيّ ثاني عشر يُضاف غدًا.

    هذا مخرَج الشحنة. قبلها كانت أربعة أسماء ناقصة (`passed_count` ·
    `failed_count` · `skipped_count` · `error_count`) لأن الصنف يسمّيها
    `*_rules`، فكان المُسلسِل يرفع `AttributeError` على كل مستند.
    """
    from apps.audit.audit_engine import AuditReport

    report = AuditReport()
    missing = sorted(n for n in _names_the_serialiser_reads()
                     if not hasattr(report, n))

    assert not missing, (
        f"AuditReport لا يعرض {missing} والمُسلسِل يقرأها ⇒ AttributeError "
        "على كل مستند، يبتلعه except Exception في المرحلة ٣ فلا يُرى.\n"
        "أضِف أسماء بديلة كـ@property — ولا تُعِد تسمية الحقول القائمة."
    )


def test_the_aliases_return_the_values_they_alias():
    """اسم بديل يُعيد قيمة أخرى أسوأ من اسم مفقود — الأول يُرى، والثاني لا."""
    from apps.audit.audit_engine import AuditReport

    report = AuditReport(total_rules=18, passed_rules=6, failed_rules=3,
                         skipped_rules=8, error_rules=1)

    assert report.passed_count == report.passed_rules == 6
    assert report.failed_count == report.failed_rules == 3
    assert report.skipped_count == report.skipped_rules == 8
    assert report.error_count == report.error_rules == 1


def test_the_original_names_still_exist():
    """الأسماء القديمة لم تُمسّ — الإضافة لا إعادة تسمية.

    مستدعون آخرون يقرأون `passed_rules`؛ وإعادة تسمية حقل يعمل لإصلاح حقل
    لا يعمل هي كيف يُكسَر مستدعٍ بصمت.
    """
    from apps.audit.audit_engine import AuditReport

    report = AuditReport()
    for name in ("passed_rules", "failed_rules", "skipped_rules", "error_rules"):
        assert name in AuditReport.__dataclass_fields__, (
            f"{name} لم يعد حقلًا في dataclass — أُعيدت تسميته لا إضافته"
        )
        assert hasattr(report, name)


def test_serialising_a_report_returns_the_counts_it_computed():
    """المُسلسِل الحقيقي على تقرير حقيقي — لا محاكاة.

    كائن مُقلَّد يجيب عن أي اسم، فيجعل عطل الاسم غير مرئي تمامًا كما فعل
    `getattr` في بوابة الحصّة.
    """
    from apps.audit.audit_engine import AuditReport
    from core.services.pipeline import _serialise_audit_report

    payload = _serialise_audit_report(
        AuditReport(total_rules=18, passed_rules=6, failed_rules=3,
                    skipped_rules=8, error_rules=1, risk_score=75,
                    risk_level="critical"))

    assert payload["total_rules"] == 18
    assert payload["passed_count"] == 6
    assert payload["failed_count"] == 3
    assert payload["skipped_count"] == 8
    assert payload["error_count"] == 1
    assert payload["risk_score"] == 75
    assert payload["risk_level"] == "critical"


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
# ٤. مخرَج الشحنة — المسار يُنتج نتيجة عبر نقطته الرسمية
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def offline_ai(monkeypatch):
    """يُبقي المحرّكات حقيقية ويقطع النداء الشبكي وحده.

    `run_full_pipeline` يثبّت `use_ai=True`، و`OPENAI_API_KEY` مضبوط في هذه
    البيئة — فاختبار يناديه كما هو يُجري نداءً خارجيًّا حقيقيًّا: بطيء،
    بكلفة، وغير حتمي. والبديل الخاطئ محاكاة المحرّكين، فتصير المرحلة ٣
    تُقاس ضد كائن يوافق على كل شيء.

    فالمُمرَّر هنا هو الصنف نفسه بوسيط واحد مقلوب. كل قاعدة وكل سطر في
    المرحلة ٣ يعمل كما في الإنتاج.
    """
    import core.services.document_engine as document_engine
    import core.services.financial_ai_engine as financial_ai_engine

    real_document = document_engine.DocumentEngine
    real_financial = financial_ai_engine.FinancialAIEngine

    def offline_document(*args, **kwargs):
        return real_document(*args, **{**kwargs, "use_ai": False})

    def offline_financial(*args, **kwargs):
        return real_financial(*args, **{**kwargs, "use_ai": False})

    monkeypatch.setattr(document_engine, "DocumentEngine", offline_document)
    monkeypatch.setattr(financial_ai_engine, "FinancialAIEngine", offline_financial)


@pytest.mark.django_db
def test_the_document_path_produces_a_result(tmp_path, settings, offline_ai):
    """`run_full_pipeline` على مستند حقيقي ⇒ `DocumentAnalysisResult` بتقرير.

    النقطة الرسمية لا الداخلية: العطل كان في المرحلة ٣ من
    `run_full_pipeline_for_file`، ويبتلعه `except Exception` هناك. اختبار
    ينادي المحرّك أو المُسلسِل وحده يتخطّى بالضبط الموضع الذي عاش فيه العطل
    150 يومًا — وهو نفس درس بوابة الحصّة.

    وأثر ثانٍ كان ضائعًا معه: الأسطر التي تُصعّد الخطورة تقع **بعد** استدعاء
    المُسلسِل، فكانت لا تُنفَّذ. مستند حكم عليه المحرّك بـcritical كان
    يُخزَّن بدرجة المرحلة ٢ وبحالة `completed`.
    """
    from django.core.files.base import ContentFile

    from apps.authentication.models import Organization
    from apps.documents.models import Document, DocumentAnalysisResult
    from core.services.pipeline import run_full_pipeline

    settings.MEDIA_ROOT = str(tmp_path)

    payload = b"invoice_number,vendor_name,total_amount\nPO-1,Acme,1150\n"
    org = Organization.objects.create(name="Pipeline Org", name_ar="أنبوب")
    doc = Document.objects.create(
        organization=org,
        document_type="purchase_order",
        file=ContentFile(payload, name="po.csv"),
        file_size=len(payload),        # NOT NULL — الرفع الحقيقي يضبطه
    )

    result = run_full_pipeline(str(doc.id))

    assert result["success"], result.get("errors")
    assert not [e for e in result.get("errors", []) if "Stage 3" in e], (
        f"المرحلة ٣ ابتلعت استثناءً: {result['errors']}"
    )

    audit = result["audit"]
    assert audit, (
        "summary['audit'] فارغ — المرحلة ٣ لم تصل إلى التخزين. هذا هو العطل "
        "الذي أصلحته هذه الشحنة."
    )
    for name in _names_the_serialiser_reads():
        assert name in audit, f"{name} غاب عن الحمولة المُسلسَلة"
    assert audit["total_rules"] > 0
    assert (audit["passed_count"] + audit["failed_count"]
            + audit["skipped_count"] + audit["error_count"]
            == audit["total_rules"])

    stored = DocumentAnalysisResult.objects.get(document=doc)
    assert stored.audit_report == audit, (
        "التقرير المُسلسَل لم يصل إلى DocumentAnalysisResult"
    )


@pytest.mark.django_db
def test_the_engines_risk_escalation_reaches_the_summary():
    """التصعيد يقع بعد سطر المُسلسِل، فكان يسقط معه.

    يُشغَّل جسم المرحلة ٣ كما هو مكتوب، بمحرّك يُعيد درجة أعلى مما أنتجته
    المرحلة ٢. لا محاكاة لكائن التقرير: `AuditReport` حقيقي.
    """
    from apps.audit.audit_engine import AuditReport
    from core.services.pipeline import _serialise_audit_report

    summary = {"risk_score": 20, "risk_level": "low", "escalate": False}
    report = AuditReport(total_rules=18, passed_rules=6, failed_rules=3,
                         skipped_rules=9, risk_score=75,
                         risk_level="critical", escalate=True)

    summary["audit"] = _serialise_audit_report(report)   # كان يرفع هنا
    if report.risk_score > summary["risk_score"]:
        summary["risk_score"] = report.risk_score
        summary["risk_level"] = report.risk_level
    if report.escalate:
        summary["escalate"] = True

    assert summary["risk_score"] == 75
    assert summary["risk_level"] == "critical"
    assert summary["escalate"] is True


# ═════════════════════════════════════════════════════════════════════════════
# ٥. الحارس يُرى وهو يفشل
# ═════════════════════════════════════════════════════════════════════════════

def test_this_guard_can_fail_when_an_alias_is_withdrawn(monkeypatch):
    """احجب `passed_count` وحده، وتأكّد أن الحارسين يريان الفرق.

    الحجب بترقيع في الاختبار لا بتحرير الملف. ولا `MagicMock` — كائن مُقلَّد
    يجيب عن أي سمة، فيخترع نجاحًا حيث لا نجاح، وهو بالضبط ما أخفى عيب بوابة
    الحصّة خلف `getattr`.
    """
    from apps.audit.audit_engine import AuditReport
    from core.services.pipeline import _serialise_audit_report

    monkeypatch.delattr(AuditReport, "passed_count")

    report = AuditReport(total_rules=18, passed_rules=6)

    # الحارس الأول: المقارنة بالاستخراج ترى الاسم ناقصًا.
    missing = [n for n in _names_the_serialiser_reads() if not hasattr(report, n)]
    assert missing == ["passed_count"], (
        f"حجب الخاصية لم يُر: {missing} — فاختبار التغطية أعلاه لا يقيسها"
    )

    # الحارس الثاني: المُسلسِل يعود إلى الانفجار الذي عاش 150 يومًا.
    with pytest.raises(AttributeError, match="passed_count"):
        _serialise_audit_report(report)


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
