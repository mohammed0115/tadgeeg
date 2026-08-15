"""`POST /api/v1/rule-engine/trigger/` — أول نقطة يستدعيها المدقّق تُحوَّل.

كانت تستورد `AuditPipeline` (V1) مباشرةً، فتقرّر الجيل عند الاستيراد وتترك
`AUDIT_ENGINE_VERSION` بلا ما تبدّله. وليس هذا نظريًّا: تشغيل كامل لمسار
الفواتير سجّل `AuditPipeline starting` و`engine_version = 2.0` والراية على
`"v2"` (`docs/INVOICE_PATH_TRACE.md`).

والتحويل مرّ عبر `run_audit_compat` بـ`engine_override="v1"` **مؤقّتًا**:
غرض الشحنة إزالة الاستيراد المباشر، لا تبديل الجيل. والانتقال إلى V2 قرار
مستقلّ يُتخذ مرّة واحدة لكل المسارات — وأثره مقيس هنا: `risk_score` يبلغ
100 حيث يقف V1 عند 90 (الانحرافان 29/34)، و`risk_level` و`blocks_approval`
لا يتغيّران.

القياس على العيّنة (5 مستندات ببصمات فريدة، من النقطة الرسمية):
صفر تغيّر حكم · صفر فرق في الحمولة · صفر خطأ · `engine_version` 2.0 → 2.0.
"""

import uuid

import pytest


def _serializer_fields() -> set[str]:
    """حقول الاستجابة كما يُعلنها المُسلسِل — لا كما أكتبها بيدي.

    قائمة يدوية في اختبار تتباعد عن الشيفرة بصمت، وهي جذر كل عيب في هذا
    المستودع.
    """
    from apps.rule_engine.serializers.audit_run_serializers import (
        AuditRunSummarySerializer,
    )
    return set(AuditRunSummarySerializer().fields)


@pytest.fixture
def org_user_and_document(db):
    """منظمة **باشتراك فعّال** ومستخدم وأمر شراء — مبنيّة هنا من الصفر.

    الاشتراك جزء من التجهيزة لا زينة: بوّابة الحصّة تُرقّع `run_audit_compat`
    وتُعيد 402 لمنظمة بلا اشتراك. والنسخة الأولى من هذا الملف تخطّت
    الاختبارات عند 402 — فمرّ **واحد من خمسة** ولم يعمل الحارس الإلزامي
    إطلاقًا. و`CLAUDE.md` بند ٣ يمنع `skip` صراحةً. العلاج أن تعمل
    الاختبارات لا أن تتخطّى.

    ⚠️ ولا تُشارَك مع أي حالة أخرى: حارسان في هذه السلسلة لوّثا ما
    يقيسانه بمشاركة كائن أو عيّنة.
    """
    from django.core.files.base import ContentFile
    from django.utils import timezone

    from apps.authentication.models import Organization, User
    from apps.billing.choices import PlanCode, SubscriptionStatus
    from apps.billing.models import OrganizationSubscription, Plan
    from apps.documents.models import Document
    from apps.documents.typed_models import PurchaseOrder

    org = Organization.objects.create(name="Trigger Co", name_ar="محفّز")

    # الخطط تُبذَر بأمر إداري لا يعمل في قاعدة الاختبار — فـ`Plan.objects`
    # فارغ، و`first()` أعاد `None` فسقط القيد `NOT NULL` على `plan_id`.
    # التجهيزة تبني خطّتها بنفسها بدل أن تفترض بذرًا.
    plan, _ = Plan.objects.get_or_create(
        code=PlanCode.BUSINESS,
        defaults={
            "name_ar": "خطة اختبار", "name_en": "Test Plan",
            "invoice_limit": 1000, "user_limit": 10,
        },
    )
    now = timezone.now()
    OrganizationSubscription.objects.create(
        organization=org, plan=plan, status=SubscriptionStatus.ACTIVE,
        starts_at=now - timezone.timedelta(days=1),
        ends_at=now + timezone.timedelta(days=30),
        invoice_limit=getattr(plan, "invoice_limit", None) or 1000,
        user_limit=getattr(plan, "user_limit", None) or 10,
        used_invoices=0,
    )

    user = User.objects.create_user(
        email=f"trigger-{uuid.uuid4().hex[:8]}@example.com",
        password="Trigger!12345",
        organization=org,
    )
    payload = b"po_number,vendor_name,total\nPO-T-1,Acme,1150\n"
    document = Document.objects.create(
        organization=org, document_type="purchase_order",
        file=ContentFile(payload, name="po.csv"), file_size=len(payload),
    )
    record = PurchaseOrder.objects.create(
        organization=org, document=document,
        po_number="PO-TRIGGER-1", vendor_name="Acme", total_amount=1150,
    )
    return org, user, record


def _trigger(client, record, document_type="purchase_order"):
    return client.post("/api/v1/rule-engine/trigger/", {
        "document_id": str(record.pk),
        "document_type": document_type,
        "triggered_by": "manual",
    }, content_type="application/json")


# ═════════════════════════════════════════════════════════════════════════════
# ١. الحمولة والتشغيل
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_the_endpoint_returns_the_same_payload_shape(client, org_user_and_document):
    """مجموعة الحقول كما يُعلنها المُسلسِل — لا أكثر ولا أقلّ."""
    _org, user, record = org_user_and_document
    client.force_login(user)

    resp = _trigger(client, record)

    assert resp.status_code == 201, (
        f"HTTP {resp.status_code} — التجهيزة تمنح اشتراكًا فعّالًا، فالرفض "
        f"هنا عطل لا حالة تُتخطّى: {resp.content[:300]}"
    )
    assert set(resp.json()) == _serializer_fields(), (
        "حمولة الاستجابة اختلفت عمّا يُعلنه المُسلسِل"
    )


@pytest.mark.django_db
def test_the_endpoint_creates_an_audit_run(client, org_user_and_document):
    """201 ⇒ صفّ `AuditRun` حقيقي بالمعرّف المُعاد."""
    from apps.rule_engine.models import AuditRun

    _org, user, record = org_user_and_document
    client.force_login(user)

    before = AuditRun.objects.count()
    resp = _trigger(client, record)

    assert resp.status_code == 201, resp.content[:300]
    assert AuditRun.objects.count() == before + 1
    run = AuditRun.objects.get(pk=resp.json()["id"])
    run.refresh_from_db()          # الانحراف 37 — لا يُقرأ كائن بائت
    assert str(run.document_id) == str(record.pk)


@pytest.mark.django_db
def test_the_endpoint_pins_v1_until_the_generation_switch(client,
                                                          org_user_and_document):
    """🔴 التثبيت على V1 مقصود — وهذا الاختبار يحرسه.

    **غرضه أن يفشل يوم يُزال التثبيت**، فيصير الانتقال إلى V2 قرارًا
    مرئيًّا لا انزلاقًا صامتًا. وأثر ذلك الانتقال مقيس: `risk_score` يبلغ
    100 حيث يقف V1 عند 90.

    ⚠️ يُحدَّث مع قرار تبديل الجيل — لا يُحذف.
    """
    _org, user, record = org_user_and_document
    client.force_login(user)

    resp = _trigger(client, record)
    assert resp.status_code == 201, resp.content[:300]

    from apps.rule_engine.models import AuditRun
    run = AuditRun.objects.get(pk=resp.json()["id"])
    run.refresh_from_db()
    assert str(run.engine_version) == "2.0", (
        f"engine_version = {run.engine_version!r} لا '2.0' — التثبيت على V1 "
        "أُزيل. إن كان ذلك مقصودًا فحدّث هذا الاختبار مع قرار تبديل الجيل، "
        "وسجّل الأثر: risk_score يبلغ 100 حيث يقف V1 عند 90."
    )


@pytest.mark.django_db
def test_tenant_isolation_still_holds(client, org_user_and_document):
    """🔴 مستخدم من منظمة لا يُدقّق سجلّ منظمة أخرى."""
    from django.core.files.base import ContentFile

    from apps.authentication.models import Organization, User
    from apps.documents.models import Document
    from apps.documents.typed_models import PurchaseOrder
    from apps.rule_engine.models import AuditRun

    _org_a, _user_a, _record_a = org_user_and_document

    org_b = Organization.objects.create(name="Other Co", name_ar="أخرى")
    payload = b"po_number\nPO-B-1\n"
    doc_b = Document.objects.create(
        organization=org_b, document_type="purchase_order",
        file=ContentFile(payload, name="b.csv"), file_size=len(payload))
    record_b = PurchaseOrder.objects.create(
        organization=org_b, document=doc_b, po_number="PO-B-1",
        vendor_name="B", total_amount=1)
    user_b = User.objects.create_user(
        email=f"b-{uuid.uuid4().hex[:8]}@example.com",
        password="Other!12345", organization=org_b)

    # (أ) يحاول تدقيق سجلّ (ب)
    client.force_login(_user_a)
    resp = _trigger(client, record_b)

    if resp.status_code == 201:
        run = AuditRun.objects.get(pk=resp.json()["id"])
        run.refresh_from_db()
        assert str(run.organization_id) != str(org_b.id), (
            "تشغيل أُنشئ تحت منظمة (ب) بطلب من مستخدم (أ) — انهار العزل"
        )
    # لا نُلزم برمز بعينه: المهمّ ألّا يُنسَب التشغيل إلى منظمة أخرى.
    assert user_b.organization_id == org_b.id


# ═════════════════════════════════════════════════════════════════════════════
# ٢. الحارس يُرى وهو يفشل
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_this_guard_can_fail(org_user_and_document):
    """أثبت أن `engine_override="v1"` هو ما يُثبّت الجيل — بإزالته.

    نفس المُدخَل، ونداءان لـ`run_audit_compat`: بالتثبيت وبدونه. فإن لم
    يختلف `engine_version` بينهما، فاختبار التثبيت أعلاه لا يقيس التثبيت.

    ⚠️ **ولا يُرقَّع `run_audit_compat` نفسه.** النسخة الأولى من هذا
    الحارس رقّعته، فوقع `RecursionError`: بوّابة الحصّة تُرقّع الوحدة عند
    الإقلاع، و`run_audit_with_quota` **يُعيد استيرادها وقت النداء**
    فيلتقط الترقيع الجديد وينادي نفسه — وهو الانحراف 32 بعينه، ما زال
    كامنًا. الحارس أيقظه، ولم يُصلحه: ذلك بند مسجَّل لا هذه الشحنة.

    ⚠️ ولا `MagicMock`: كائن مُقلَّد يجيب عن أي سمة فيخترع نجاحًا.
    """
    from django.core.files.base import ContentFile

    from apps.documents.models import Document
    from apps.documents.typed_models import PurchaseOrder
    from apps.rule_engine.pipeline.v2.compat import run_audit_compat

    org, _user, record = org_user_and_document

    # سجلّ ثانٍ مستقلّ للحالة الثانية — لا `force_rerun` على الأول.
    # إعادة التشغيل تستهلك حصّة فتطلب البوّابة تأكيدًا صريحًا، وهو سلوك
    # صحيح لا يُلتفّ عليه. وبناء مُدخَل مستقلّ هو القاعدة نفسها التي
    # سقط عندها حارسان في هذه السلسلة.
    payload = b"po_number,vendor_name,total\nPO-T-2,Acme,1150\n"
    second_doc = Document.objects.create(
        organization=org, document_type="purchase_order",
        file=ContentFile(payload, name="po2.csv"), file_size=len(payload))
    second = PurchaseOrder.objects.create(
        organization=org, document=second_doc,
        po_number="PO-TRIGGER-2", vendor_name="Acme", total_amount=1150)

    pinned = run_audit_compat(
        document_id=str(record.pk), document_type="purchase_order",
        organization_id=str(org.id), triggered_by="manual",
        engine_override="v1",
    )
    pinned.refresh_from_db()

    unpinned = run_audit_compat(
        document_id=str(second.pk), document_type="purchase_order",
        organization_id=str(org.id), triggered_by="manual",
    )
    unpinned.refresh_from_db()

    assert str(pinned.engine_version) == "2.0"
    assert str(unpinned.engine_version) != str(pinned.engine_version), (
        f"إزالة التثبيت لم تُغيّر الجيل (كلاهما "
        f"{pinned.engine_version!r}) — فاختبار التثبيت أعلاه لا يقيس ما "
        "يدّعيه"
    )
