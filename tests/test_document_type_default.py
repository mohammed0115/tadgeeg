"""`document_type` الغائب يُقال «مجهول» ولا يُخمَّن «فاتورة».

`core/services/normalization.py` كان يضع `"invoice"` حين لا يستخرج المحلّل
نوعًا — بين سطرين يقولان `"unknown"` للحالة نفسها بالضبط:

    "extraction_method": … or "unknown",
    "document_type":     … or "invoice",      ← هذا
    "language":          … or "unknown",

والحقل الوحيد من الثلاثة الذي **يقرّر أي قواعد تُطبَّق** هو الأوسط.

ثم `document_classifier._classify_structural` يقرأ ذلك الافتراض ويُعيده
**بثقة 0.90 كتحديد بنيوي** — فيدخل تخمينًا ويخرج قياسًا. 17 من 34 مستندًا
مقيسًا سلكت هذا الطريق، ولا واحد منها من الكلمات المفتاحية ولا من الذكاء
الاصطناعي (`docs/CLASSIFICATION_MEASUREMENT.md`).

الأثر ليس تجميليًّا: `R017` طالب عقدًا برمز ZATCA، و`R018` طالب كشف عميل
بحقول فاتورة — ملاحظات كاذبة تُعرض لمدقق.

🔴 **الاختبار الثاني هنا حارس نمط لا حالة**: افتراض يُعرض كقياس. وهو النمط
الذي أنتج «30 قاعدة» وقائمة `Callers:` و`testpaths` في هذا المستودع.
"""

import pytest


# ═════════════════════════════════════════════════════════════════════════════
# ١. الافتراض لا يخمّن
# ═════════════════════════════════════════════════════════════════════════════

def test_an_absent_type_is_not_guessed():
    """حمولة بلا `document_type` ⇒ الناتج ليس «فاتورة»."""
    from core.services.normalization import NormalizationService

    out = NormalizationService().normalize(
        {"total_amount": 100, "raw_text": "some contract text"}
    ).to_serializable_dict()

    assert out["document_type"] != "invoice", (
        "الافتراض عاد إلى التخمين — والحقل يقرّر أي قواعد تُطبَّق"
    )
    assert out["document_type"] == "unknown"


def test_the_absent_type_matches_what_its_neighbours_say():
    """السطران المجاوران يقولان «unknown» للحالة نفسها.

    اتّساق الحقول الثلاثة مقصود: كلها تعني «لم يُستخرَج»، فيجب أن تقولها
    بالكلمة نفسها. اختلافها هو ما جعل الشذوذ غير مرئي سنوات.
    """
    from core.services.normalization import NormalizationService

    out = NormalizationService().normalize({"total_amount": 1}).to_serializable_dict()

    assert out["extraction_method"] == "unknown"
    assert out["language"] == "unknown"
    assert out["document_type"] == "unknown"


def test_a_present_type_is_passed_through_untouched():
    """التصحيح يمسّ الغياب وحده — قيمة موجودة تمرّ كما هي."""
    from core.services.normalization import NormalizationService

    out = NormalizationService().normalize(
        {"document_type": "bank_statement", "total_amount": 1}
    ).to_serializable_dict()

    assert out["document_type"] == "bank_statement"


# ═════════════════════════════════════════════════════════════════════════════
# ٢. 🔴 المُصنِّف لا يُصادق على افتراض — حارس نمط
# ═════════════════════════════════════════════════════════════════════════════

def test_the_classifier_does_not_certify_a_default():
    """قيمة تعني «لم يُحدَّد» ⇒ لا `structural` ولا 0.90.

    هذا هو العطل نفسه: الفرع البنيوي كان يختم افتراضًا بثقة عالية ويُغلق
    الطريق على الفرعين اللذين ينظران إلى المستند فعلًا.
    """
    from core.services.classification.document_classifier import DocumentClassifier

    clf = DocumentClassifier()

    for sentinel in ("unknown", ""):
        result = clf._classify_structural({"document_type": sentinel})
        assert result is None or result["document_type"] != sentinel, (
            f"الفرع البنيوي صادق على {sentinel!r} — الافتراض يُعرض كقياس"
        )
        if result is not None:
            assert result["confidence"] < 0.90, (
                f"ثقة 0.90 على قيمة لم يُحدّدها أحد: {result}"
            )


def test_an_undetermined_type_falls_through_to_the_looking_branches():
    """الرفض ليس صمتًا: القيمة تمضي إلى الكلمات المفتاحية.

    مستند نصّه يقول «bank statement» ويحمل `document_type="unknown"` يجب أن
    يُصنَّف كشف حساب — لا أن يُغلق عليه الفرع البنيوي.
    """
    from core.services.classification.document_classifier import DocumentClassifier

    out = DocumentClassifier().classify(
        raw_text="Bank Statement — opening balance and closing balance for the period",
        structured={"document_type": "unknown"},
        use_ai=False,
    )
    assert out["method"] != "structural"
    assert out["document_type"] != "unknown", (
        "القيمة الحارسة تسرّبت كنوع مستند بدل أن تُستبدَل بتصنيف"
    )


def test_a_real_structural_determination_is_still_certified():
    """البوّابة تفتح كما تُغلق — وإلّا فهي كتم لا تمييز."""
    from core.services.classification.document_classifier import DocumentClassifier

    result = DocumentClassifier()._classify_structural(
        {"document_type": "purchase_order"})

    assert result is not None
    assert result["document_type"] == "purchase_order"
    assert result["confidence"] == 0.90
    assert result["method"] == "structural"


def test_the_sentinel_set_is_read_from_the_module():
    """القائمة ليست مكتوبة هنا — تُقرأ من حيث تُستعمل.

    قائمة يدوية في اختبار تتباعد عن الشيفرة بصمت، وهي جذر كل عيب في هذا
    المستودع.
    """
    from core.services.classification.document_classifier import (
        _UNDETERMINED, DOCUMENT_TYPES,
    )

    assert "unknown" in _UNDETERMINED
    assert "unknown" not in DOCUMENT_TYPES, (
        "«unknown» صار نوع مستند — وهو ليس نوعًا بل غيابه"
    )


# ═════════════════════════════════════════════════════════════════════════════
# ٣. الخريطة تُسجّل ما يسقط منها
# ═════════════════════════════════════════════════════════════════════════════

def test_an_unmapped_type_is_recorded_not_swallowed(caplog):
    """قيمة خارج `type_map` ⇒ تُسجَّل، ولا تُوقف رفعًا.

    مُصنِّف يتّسع بقيمة جديدة ولا أحد يلاحظ = نوع مستند لا يُدقَّق. والتسجيل
    لا الاستثناء: قيمة جديدة يجب ألّا تُسقِط رفعًا.
    """
    import ast
    import inspect
    import textwrap

    import core.services.pipeline as pipeline_module

    # `ast` لا تقطيع نصّ: النسخة الأولى من هذا الاختبار قصّت 400 حرف بعد
    # الشرط، وتعليق الشيفرة كان أطول منها — فأبلغت عن غياب تسجيل موجود.
    tree = ast.parse(textwrap.dedent(
        inspect.getsource(pipeline_module._persist_result)))

    guards = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.If) and "type_map" in ast.dump(n.test)
        and isinstance(n.test, ast.Compare)
        and any(isinstance(o, ast.NotIn) for o in n.test.ops)
    ]
    assert guards, (
        "لا فحص للقيم غير المخرَّطة — قيمة جديدة تسقط إلى 'other' بصمت"
    )
    body = guards[0].body

    logged = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr in {"info", "warning", "error"}
        for stmt in body for n in ast.walk(stmt)
    )
    assert logged, "القيمة غير المخرَّطة لا تُسجَّل"

    raised = any(isinstance(n, ast.Raise)
                 for stmt in body for n in ast.walk(stmt))
    assert not raised, (
        "القيمة غير المخرَّطة تُوقف الرفع — يجب أن تُسجَّل لا أن ترفع"
    )


def test_unknown_never_reaches_the_document_type_column():
    """«unknown» ليس خيارًا في `DocumentType` — والخريطة تحميه من الوصول."""
    from apps.documents.models import Document

    choices = {k for k, _ in Document.DocumentType.choices}
    assert "unknown" not in choices

    # نفس الخريطة التي يستعملها _persist_result، مقروءة من مصدرها.
    import inspect
    import core.services.pipeline as pipeline_module

    source = inspect.getsource(pipeline_module._persist_result)
    assert 'type_map.get(ai_type, "other")' in source, (
        "المسار الذي يمنع «unknown» من بلوغ العمود تغيّر"
    )


# ═════════════════════════════════════════════════════════════════════════════
# ٤. الحارس يُرى وهو يفشل
# ═════════════════════════════════════════════════════════════════════════════

def test_this_guard_can_fail(monkeypatch):
    """أعِد «invoice» بترقيع، وتأكّد أن الحارسين يريان الفرق.

    الترقيع في الاختبار لا في الملف. ولا `MagicMock`: كائن مُقلَّد يجيب عن
    أي سمة فيخترع نجاحًا — وهو ما أخفى عيب بوابة الحصّة خلف `getattr`.
    """
    from core.services.normalization import NormalizationService
    from core.services.classification.document_classifier import DocumentClassifier

    svc = NormalizationService()
    real_normalize = svc.normalize

    # ١. الحال الصحيح.
    assert real_normalize({"total_amount": 1}).to_serializable_dict()[
        "document_type"] == "unknown"

    # ٢. أعِد العيب: احشُ الافتراض القديم في الحمولة قبل التطبيع.
    def guessing_normalize(payload, *a, **k):
        return real_normalize({**payload, "document_type": "invoice"}, *a, **k)

    monkeypatch.setattr(svc, "normalize", guessing_normalize)
    out = svc.normalize({"total_amount": 1}).to_serializable_dict()
    assert out["document_type"] == "invoice", (
        "زرع الافتراض القديم لم يُغيّر شيئًا — فاختبار الافتراض أعلاه "
        "لا يقيس ما يدّعيه"
    )

    # ٣. والمُصنِّف يُصادق عليه بـ0.90 — وهي الحلقة الكاملة للعيب.
    certified = DocumentClassifier()._classify_structural(out)
    assert certified is not None
    assert certified["confidence"] == 0.90 and certified["method"] == "structural", (
        "الفرع البنيوي لم يعد يُصادق على «invoice» — فاختبار المُصادقة "
        "أعلاه لا يقيس ما يدّعيه"
    )
