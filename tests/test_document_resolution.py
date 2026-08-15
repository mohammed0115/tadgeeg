"""من `Document` إلى السجل المُطبوع — والعطل الذي عاش لأنه لا يرفع.

`run_audit_compat(document_id, document_type)` لا يأخذ مفتاح `Document`.
`document_id` مفتاح السجل **المُطبوع**، والمُطبِّع يبحث به مباشرةً:

    po = PurchaseOrder.objects.get(id=document_id)

و`apps/audit/tasks.py` كان يمرّر `doc.pk` مع `document_type="sales_invoice"`.
التقاطع بين فضاءَي المفاتيح **صفر** — فيقع `Invoice.DoesNotExist`، **ولا
يُرفع**: المُطبِّع يسجّل تحذيرًا ويُعيد `NormalizedDocument` فارغًا، فتُنشئ
المهمّة `AuditRun` على مستند لم تقرأه وتحسبه تدقيقًا.

مقيسًا بيدي: `typed_data == {}` بلا استثناء، و`document.purchaseorder` يحمل
**15 حقلًا** في اللحظة نفسها.

والخريطة هنا **محسوبة لا مكتوبة**: العلاقات العكسية من Django، وأسماء
الأنواع من سجل المُطبِّعات. واشتقاق الاسم مرفوض عمدًا — يطابق 15 من 20
ويكسر `ExpenseReport→expense` · `GoodsReceiptNote→grn` ·
`PaymentVoucher→payment` · `PayrollSheet→payroll` · و`VATReturn` الذي
يشتقّ إلى `v_a_t_return`.
"""

import uuid

import pytest


# ═════════════════════════════════════════════════════════════════════════════
# ١. الخريطة محسوبة — وتامّة في الاتجاهين
# ═════════════════════════════════════════════════════════════════════════════

def test_every_typed_record_on_document_has_a_normalizer():
    """كل نموذج مطبوع يبلغه `Document` يعرفه سجل المُطبِّعات.

    🔴 **يفشل عند نوع جديد بلا مُطبِّع** — وهذا غرضه: نموذج يُضاف ولا
    مُطبِّع له هو نوع مستند لا يُدقَّق، ولا شيء آخر يقول ذلك.
    """
    from apps.documents.models import Document
    from core.document_resolution import typed_model_to_document_type

    known = typed_model_to_document_type()
    reverse_models = {
        f.related_model.__name__
        for f in Document._meta.get_fields()
        if f.auto_created and not f.concrete and f.one_to_one
    } - {"ExtractedData", "DocumentAnalysisResult"}

    missing = sorted(reverse_models - set(known))
    assert not missing, (
        f"نماذج مطبوعة على Document بلا مُطبِّع مسجَّل: {missing}\n"
        "كل واحد منها نوع مستند يُرفَع ولا يُدقَّق."
    )


def test_the_map_is_not_derived_from_model_names():
    """الاشتقاق يطابق 15 من 20 — والخمسة الباقية هي الاختبار.

    لو استُبدلت الخريطة المحسوبة باشتقاق `snake_case` يومًا، تسقط هذه
    الأسماء الخمسة بالضبط.
    """
    from core.document_resolution import typed_model_to_document_type

    mapping = typed_model_to_document_type()
    for model_name, expected in (
        ("ExpenseReport", "expense"),
        ("GoodsReceiptNote", "grn"),
        ("PaymentVoucher", "payment"),
        ("PayrollSheet", "payroll"),
        ("VATReturn", "tax_return"),
    ):
        assert mapping.get(model_name) == expected, (
            f"{model_name} يُخرَّط إلى {mapping.get(model_name)!r} والمسجَّل "
            f"{expected!r} — الخريطة صارت اشتقاقًا لا قراءة من السجل"
        )


def test_sales_invoice_never_takes_part_in_resolution():
    """`sales_invoice` يُطبِّع `invoices.Invoice`، و`Document` لا يبلغه.

    الخريطة تحويه لأنها تقرأ سجل المُطبِّعات كاملًا — وهذا صحيح. لكن الحلّ
    يمرّ بالعلاقات العكسية على `Document` وحدها، و`Invoice` ليس فيها. فمسار
    الفواتير لا يُمَسّ من هنا بأي حال.

    (النسخة الأولى من هذا الاختبار ادّعت أن `Invoice` خارج الخريطة، بناءً
    على استخراج أضيق لم يكن يرى `Invoice.objects.select_related(…).get(…)`.
    الادّعاء كان عن أداتي لا عن الشيفرة.)
    """
    from apps.documents.models import Document
    from core.document_resolution import typed_accessors

    reverse_models = {model for _, model in typed_accessors()}
    assert "Invoice" not in reverse_models, (
        "صار `Invoice` قابلًا للبلوغ من `Document` — أعِد قراءة الشحنة"
    )
    assert "Invoice" not in {
        f.related_model.__name__ for f in Document._meta.get_fields()
        if f.auto_created and not f.concrete and f.one_to_one
    }



# ── تجهيزة: مستند حقيقي بسجل مُطبوع حقيقي ───────────────────────────────────
#
# 🔴 النسخة الأولى من الاختبارات أدناه كانت تقرأ `Document.objects.all()[:200]`
# — وقاعدة pytest **فارغة**. فمرّت الأربعة على «لا شيء» وأبلغت عن نجاح لا
# يقيس شيئًا، حتى أضفتُ `assert checked > 0` فانكشفت. وهو الانحراف 58 نفسه:
# اختبار كُتب على كوربوس dev ويعمل على قاعدة أخرى.

@pytest.fixture
def document_with_typed_record(db):
    """`(document, purchase_order)` — مستند وسجله المُطبوع، مبنيّان هنا."""
    from django.core.files.base import ContentFile

    from apps.authentication.models import Organization
    from apps.documents.models import Document
    from apps.documents.typed_models import PurchaseOrder

    org = Organization.objects.create(name="Resolve Co", name_ar="شركة الحلّ")
    payload = b"po_number,vendor_name,total\nPO-1,Acme,1150\n"
    document = Document.objects.create(
        organization=org,
        document_type="purchase_order",
        file=ContentFile(payload, name="po.csv"),
        file_size=len(payload),
    )
    record = PurchaseOrder.objects.create(
        organization=org,
        document=document,
        po_number="PO-RESOLVE-1",
        vendor_name="Acme",
        total_amount=1150,
    )
    return document, record


# ═════════════════════════════════════════════════════════════════════════════
# ٢. الحلّ على مستندات حقيقية
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_every_document_resolves_to_its_typed_record(document_with_typed_record):
    """السجل المُعاد هو سجل هذا المستند بعينه — لا سجلًّا من نوعه."""
    from core.document_resolution import resolve, typed_model_to_document_type

    document, expected = document_with_typed_record
    record, document_type = resolve(document)

    assert record.pk == expected.pk, "حُلّ إلى سجل ليس سجله"
    assert document_type == "purchase_order"
    assert document_type in set(typed_model_to_document_type().values())


@pytest.mark.django_db
def test_an_unresolvable_document_fails_loudly():
    """بلا سجل مُطبوع ⇒ استثناء يسمّي المستند · لا حمولة فارغة.

    هذا هو الفرق كلّه: العطل عاش لأن الفشل كان صامتًا.
    """
    from django.core.files.base import ContentFile

    from apps.authentication.models import Organization
    from apps.documents.models import Document
    from core.document_resolution import UnresolvedDocument, resolve

    org = Organization.objects.create(name="Res Org", name_ar="حلّ")
    payload = b"a,b\n1,2\n"
    orphan = Document.objects.create(
        organization=org,
        document_type="purchase_order",   # التسمية تدّعي، ولا سجل خلفها
        file=ContentFile(payload, name="orphan.csv"),
        file_size=len(payload),
    )

    with pytest.raises(UnresolvedDocument) as caught:
        resolve(orphan)

    assert str(orphan.pk) in str(caught.value), (
        "الاستثناء لا يسمّي المستند — فالمشغّل لا يعرف أيّها فشل"
    )


@pytest.mark.django_db
def test_the_resolved_record_normalises_to_a_non_empty_document(
    document_with_typed_record,
):
    """🔴 مخرَج الشحنة: المفتاح المُعاد يجد سجلًّا، والحمولة ليست فارغة."""
    from apps.rule_engine.normalizers import DocumentNormalizerFactory
    from core.document_resolution import resolve

    document, _ = document_with_typed_record
    record, document_type = resolve(document)

    normalized = DocumentNormalizerFactory.get(document_type).normalize(
        str(record.pk), str(document.organization_id))

    assert getattr(normalized, "typed_data", None), (
        f"المُطبِّع {document_type!r} أعاد حمولة فارغة للمفتاح المُعاد "
        f"{record.pk} — الحلّ لم يُصلح شيئًا"
    )


# ═════════════════════════════════════════════════════════════════════════════
# ٣. المهمّة المجدولة لم تعد تمرّر مفتاح Document
# ═════════════════════════════════════════════════════════════════════════════

def test_the_scheduled_task_no_longer_passes_a_document_key_as_invoice_id():
    """موضع الاستدعاء يُقرأ من المصدر بالـ`ast` لا بتقطيع نصّ.

    (النسخة الأولى من اختبار مشابه في هذا المستودع قصّت 400 حرف فأبلغت عن
    غياب سطر موجود.)
    """
    import ast
    import inspect
    import textwrap

    import apps.audit.tasks as tasks

    tree = ast.parse(textwrap.dedent(
        inspect.getsource(tasks.audit_high_risk_documents)))

    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr in ("evaluate", "evaluate_document")
    ]
    assert calls, "لم يعد يُستدعى المحوّل إطلاقًا في هذه المهمّة"

    for call in calls:
        kwargs = {k.arg for k in call.keywords}
        assert "invoice_id" not in kwargs, (
            "المهمّة عادت تمرّر invoice_id — وهو مفتاح Document في هذا "
            "الموضع، فيُبحَث به في جدول Invoice ولا يُوجد"
        )
        assert call.func.attr == "evaluate_document", (
            f"المهمّة تنادي {call.func.attr!r} لا evaluate_document"
        )


def test_the_invoices_path_entry_point_is_untouched():
    """`evaluate` القائمة لم تُمسّ — مسار الفواتير حيّ ولا يُغيَّر."""
    import inspect

    from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
        LegacyAuditEngineAdapter,
    )

    source = inspect.getsource(LegacyAuditEngineAdapter.evaluate)
    assert 'raise ValueError("LegacyAuditEngineAdapter.evaluate() requires invoice_id")' in source
    assert 'document_type="sales_invoice"' in source


# ═════════════════════════════════════════════════════════════════════════════
# ٤. الحارس يُرى وهو يفشل
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_this_guard_can_fail(document_with_typed_record):
    """أعِد `doc.pk` بترقيع، وتأكّد أن الحمولة تعود فارغة.

    الترقيع في الاختبار لا في الملف. ولا `MagicMock`: كائن مُقلَّد يجيب عن
    أي سمة فيخترع نجاحًا — وهو ما أخفى عيب بوابة الحصّة خلف `getattr`.
    """
    from apps.rule_engine.normalizers import DocumentNormalizerFactory
    from core.document_resolution import resolve

    document, _ = document_with_typed_record
    record, document_type = resolve(document)
    normalizer = DocumentNormalizerFactory.get(document_type)
    org = str(document.organization_id)

    # الحال الصحيح: المفتاح المُعاد يُنتج حمولة.
    good = normalizer.normalize(str(record.pk), org)
    assert getattr(good, "typed_data", None)

    # العيب يعود بالضبط: مفتاح Document في المُطبِّع نفسه.
    bad = normalizer.normalize(str(document.pk), org)
    assert not getattr(bad, "typed_data", None), (
        "تمرير مفتاح Document لم يُعِد الحمولة فارغة — فالاختبارات أعلاه "
        "لا تقيس فرق فضاءَي المعرّفات"
    )

    # ولا يرفع — وهو سبب صمت العطل طوال الوقت.
    assert bad is not None
    assert str(getattr(bad, "document_id", "")) == str(document.pk)
