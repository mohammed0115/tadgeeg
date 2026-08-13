"""الخطوة ٢ — عقد الجسر مُختبَرًا لا موصوفًا.

الموضع: tests/test_adapter_contract.py

**لماذا هذا الملف.** `legacy_audit_adapter.AuditRunResult` كان موسومًا
"Drop-in replacement" وتوثيقه يعلن التزام Liskov — ولم يكن كذلك: استبداله في
`core/services/pipeline.py` يرفع AttributeError على سبعة حقول. الادّعاء كان
نصًّا، والنصّ لا يستطيع أن يفشل.

هذا الملف يحوّل الادّعاء إلى شيء يفشل. وهو **يقرأ الحقول من الشيفرة نفسها**
بدل قائمة مكتوبة بيد — لأن القائمة اليدوية هي الجذر الذي أوقعنا في المشكلة
أصلًا (قائمة `Callers:` في رأس الجسر كانت 3 من 4).
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from django.conf import settings


# ── الحقول التي يقرأها كل مستدعٍ — محسوبة لا مكتوبة ──────────────────────────

#: المستدعون الذين يستلمون كائن تقرير من الجسر. توسيع هذه القائمة مسموح؛
#: المهم أن الحقول داخل كل ملف تُستخرَج آليًا لا يدويًا.
_REPORT_CONSUMERS = {
    "core/services/pipeline.py": ("report",),
    "apps/audit/tasks.py": ("report",),
}


def _attributes_read_from(path: Path, var_names: tuple[str, ...]) -> set[str]:
    """كل `<var>.<attr>` يُقرأ في ملف، بالـAST لا بالتعبير النمطي.

    التعبير النمطي كان سيلتقط `report.risk_score` في تعليق أو نصّ، والـAST لا
    يفعل. وهذا مقصود: الحارس الذي يلتقط ما ليس مخالفًا يُسكَت بعد أول إنذار
    كاذب.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        value = node.value
        if isinstance(value, ast.Name) and value.id in var_names:
            found.add(node.attr)
    return found


def _expected_contract() -> dict[str, set[str]]:
    base = Path(settings.BASE_DIR)
    contract: dict[str, set[str]] = {}
    for rel, var_names in _REPORT_CONSUMERS.items():
        path = base / rel
        if not path.exists():          # الملف نُقل أو حُذف — لا تفشل صامتًا
            pytest.fail(
                f"{rel} غير موجود. إن نُقل، حدّث _REPORT_CONSUMERS؛ وإن حُذف، "
                f"احذف مدخله — عقد بلا مستدعٍ ليس عقدًا."
            )
        contract[rel] = _attributes_read_from(path, var_names)
    return contract


# ── الاختبارات ───────────────────────────────────────────────────────────────


def test_adapter_exposes_every_field_its_consumers_read():
    """كل حقل يقرأه أي مستدعٍ موجود على الجسر.

    يفشل حين يبدأ مستدعٍ بقراءة حقل ثامن — قبل الإنتاج لا بعده.
    """
    from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
        AuditRunResult,
    )

    exposed = {
        name for name in dir(AuditRunResult)
        if not name.startswith("_")
    }
    # الخصائص المُعرَّفة في __init__ لا تظهر في dir() على الصنف، فتُقرأ من المصدر.
    src = inspect.getsource(AuditRunResult.__init__)
    exposed |= {
        node.targets[0].attr
        for node in ast.walk(ast.parse(src.strip().replace("\n    ", "\n")))
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Attribute)
        and isinstance(node.targets[0].value, ast.Name)
        and node.targets[0].value.id == "self"
        and not node.targets[0].attr.startswith("_")
    }

    missing: dict[str, set[str]] = {}
    for rel, attrs in _expected_contract().items():
        gap = attrs - exposed
        if gap:
            missing[rel] = gap

    assert not missing, (
        "الجسر لا يوفّر حقولًا يقرأها مستدعوه:\n"
        + "\n".join(f"  {rel}: {sorted(gap)}" for rel, gap in missing.items())
        + "\n\nهذا هو العيب نفسه الذي أُنشئ هذا الاختبار لأجله: الجسر يُوسَم "
          "'drop-in' ولا يُرضي عقد مستدعٍ. أضف الحقل إلى AuditRunResult — "
          "لا تُضعِف هذا الاختبار."
    )


@pytest.mark.django_db
def test_adapter_fields_carry_real_values(django_user_model):
    """الحقول موجودة **وتحمل قيمًا صحيحة** من AuditRun.

    حقل موجود بقيمة None يمرّ اختبار الوجود ويكسر الإنتاج. فالوجود لا يكفي.
    """
    from apps.rule_engine.models import AuditRun
    from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
        AuditRunResult,
    )
    from apps.authentication.models import Organization

    org = Organization.objects.create(name="Contract Test Org")
    run = AuditRun.objects.create(
        organization=org,
        document_type="sales_invoice",
        document_id="00000000-0000-0000-0000-000000000001",
        total_rules=10,
        passed_rules=6,
        failed_rules=3,
        warning_rules=1,
        skipped_rules=0,
        error_rules=0,
        risk_score=42.5,
        risk_level="medium",
    )

    result = AuditRunResult(run)

    assert result.total_rules == 10
    assert result.passed_count == 6
    assert result.failed_count == 3
    assert result.skipped_count == 0
    assert result.error_count == 0
    assert result.risk_score == 42.5
    assert result.risk_level == "medium"
    assert isinstance(result.processing_time_ms, int)
    assert "10 rules" in result.summary
    assert result.rule_results == []          # لا نتائج ⇒ قائمة فارغة لا None

    # الأسماء القديمة لم تُكسَر — apps/audit/tasks.py يقرأها
    assert result.passed_rules == result.passed_count
    assert result.failed_rules == result.failed_count


def test_this_guard_can_fail():
    """⚠️ إلزامي — إثبات أن الحارس يلتقط مخالفًا.

    حارس لم يُر وهو يفشل ليس حارسًا. الدرس من commit 3d29066: حارس السلاسل
    اليدوية تخطّى أي ملف يحتوي السلسلة "HashChainMixin"، والـcommit الذي أدخله
    وضع تلك السلسلة في الملف الوحيد المخالف — فأبلغ عن صفر مخالفات منذ ولادته.
    """
    src = "def f(report):\n    return report.a_field_that_does_not_exist\n"
    tree = ast.parse(src)
    attrs = {
        n.attr for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "report"
    }
    assert attrs == {"a_field_that_does_not_exist"}, (
        "مستخرِج الحقول لا يعمل — فالاختبار الأساسي أعلاه يمرّ بلا أن يفحص شيئًا."
    )


# ═════════════════════════════════════════════════════════════════════════════
# الغلاف يقرأ الصفّ المحفوظ — لا نسخة الذاكرة
#
# `AuditRunResult.__init__` كان يقرأ الكائن الذي يُعيده الأنبوب، وهو **بائت
# بالضرورة لا بالصدفة**: الأنبوب يُنشئ `AuditRun` مبكرًا، ومراحله اللاحقة
# تكتب على الصفّ بـ`save(update_fields=…)` و`queryset.update()` — ولا واحدة
# منهما تُنعش الكائن الذي يمسكه المستدعي.
#
# مقيسًا على تشغيل حقيقي، الغلاف مقابل القاعدة:
#     total_rules  20 مقابل 19 · skipped 15 مقابل 14
#     risk_score 50.0 مقابل 100.0 · risk_level high مقابل critical
#
# و`apps/audit/tasks.py` يقرأ `escalate` من هذا الكائن ليقرّر التصعيد. فعلى
# تشغيل حكم عليه المحرّك بـcritical ومحجوب، كان يقرأ أرقامًا هادئة.
# ═════════════════════════════════════════════════════════════════════════════

def _run_for(org, **overrides):
    from apps.rule_engine.models import AuditRun

    defaults = dict(
        organization=org,
        document_type="sales_invoice",
        document_id="00000000-0000-0000-0000-000000000002",
        total_rules=0, passed_rules=0, failed_rules=0, warning_rules=0,
        skipped_rules=0, error_rules=0, risk_score=0, risk_level="low",
        blocks_approval=False, requires_manual_review=False,
    )
    defaults.update(overrides)
    return AuditRun.objects.create(**defaults)


@pytest.mark.django_db
def test_the_wrapper_reads_the_saved_row_not_the_in_memory_one():
    """🔴 الحارس الأساسي.

    `queryset.update()` يكتب في القاعدة **ولا يمسّ كائن الذاكرة** — وهو
    بالضبط ما تفعله مراحل الأنبوب. فالكائن المُمرَّر إلى الغلاف يبقى على
    قيم الإنشاء، والغلاف يجب أن يتجاوزه إلى الصفّ.
    """
    from apps.authentication.models import Organization
    from apps.rule_engine.models import AuditRun
    from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
        AuditRunResult,
    )

    org = Organization.objects.create(name="Stale Org", name_ar="بائت")
    run = _run_for(org)

    AuditRun.objects.filter(pk=run.pk).update(
        total_rules=19, passed_rules=4, failed_rules=1, skipped_rules=14,
        error_rules=0, warning_rules=0, risk_score=100, risk_level="critical",
    )
    # الكائن الذي بيدنا ما زال على قيم الإنشاء — وهذا هو شرط الاختبار.
    assert run.total_rules == 0 and run.risk_level == "low"

    wrapped = AuditRunResult.from_audit_run(run)

    assert wrapped.total_rules == 19, (
        f"الغلاف قرأ {wrapped.total_rules} — نسخة الذاكرة لا الصفّ المحفوظ"
    )
    assert wrapped.passed_count == 4
    assert wrapped.failed_count == 1
    assert wrapped.skipped_count == 14
    assert wrapped.risk_score == 100.0
    assert wrapped.risk_level == "critical"


@pytest.mark.django_db
def test_escalate_reflects_a_blocked_run():
    """`blocks_approval=True` ⇒ `escalate=True`.

    هذا ما كان يفشل صامتًا: المهمّة الليلية تقرأ `escalate` لتقرّر التصعيد،
    فكانت تقرأ `False` على تشغيل محجوب.
    """
    from apps.authentication.models import Organization
    from apps.rule_engine.models import AuditRun
    from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
        AuditRunResult,
    )

    org = Organization.objects.create(name="Block Org", name_ar="حجب")
    run = _run_for(org)
    AuditRun.objects.filter(pk=run.pk).update(
        blocks_approval=True, requires_manual_review=True,
        risk_score=100, risk_level="critical",
    )
    assert run.blocks_approval is False        # الذاكرة ما زالت هادئة

    assert AuditRunResult.from_audit_run(run).escalate is True, (
        "تشغيل محجوب لم يُصعَّد — وهو العَرَض الذي عاش صامتًا"
    )


@pytest.mark.django_db
def test_an_unsaved_run_does_not_raise():
    """كائن بلا `pk` لا يُنعَش ولا يُسقِط الغلاف.

    غلاف يرفع أسوأ من غلاف يقرأ قيمًا قديمة: الأول يوقف مسارًا.
    """
    from apps.rule_engine.models import AuditRun
    from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
        AuditRunResult,
    )

    unsaved = AuditRun(
        document_type="sales_invoice", total_rules=7, passed_rules=7,
        failed_rules=0, warning_rules=0, skipped_rules=0, error_rules=0,
        risk_score=5, risk_level="low",
    )
    # 🔴 `pk` موجود **رغم أنه غير محفوظ**: مفتاح AuditRun
    # `UUIDField(default=uuid4)`، فالقيمة تُولَّد عند الإنشاء لا عند الحفظ.
    # النسخة الأولى من هذا الاختبار افترضت `pk is None` — وكشف فشلُه أن
    # الفحص في الغلاف كان يرسل كائنًا غير محفوظ إلى القاعدة. الفحص الصحيح
    # هو `_state.adding`، وهو ما تسأله Django نفسها.
    assert unsaved.pk is not None
    assert unsaved._state.adding is True

    wrapped = AuditRunResult.from_audit_run(unsaved)
    assert wrapped.total_rules == 7
    assert wrapped.risk_level == "low"


@pytest.mark.django_db
def test_a_deleted_run_is_warned_about_not_swallowed(caplog):
    """صفّ حُذف بين التنفيذ واللفّ ⇒ تحذير مسجَّل، لا صمت ولا استثناء."""
    import logging

    from apps.authentication.models import Organization
    from apps.rule_engine.models import AuditRun
    from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
        AuditRunResult,
    )

    org = Organization.objects.create(name="Gone Org", name_ar="محذوف")
    run = _run_for(org, total_rules=3)
    pk = run.pk
    AuditRun.objects.filter(pk=pk).delete()

    with caplog.at_level(logging.WARNING, logger="rule_engine.pipeline"):
        wrapped = AuditRunResult.from_audit_run(run)

    assert wrapped.total_rules == 3          # قيم الذاكرة، وهي كل ما بقي
    assert any("could not refresh" in r.getMessage() for r in caplog.records), (
        "الفشل ابتُلع صامتًا — والصمت هو ما جعل هذا العطل يعيش"
    )


@pytest.mark.django_db
def test_this_guard_can_fail(monkeypatch):
    """احجب الإنعاش بترقيع، وتأكّد أن الحارس الأول يراه.

    الترقيع في الاختبار لا في الملف. ولا `MagicMock`: كائن مُقلَّد يجيب عن
    أي سمة فيخترع نجاحًا.

    ⚠️ وكل حالة تُبنى بكائن **مستقلّ**: النسخة الأولى لفّت الكائن نفسه
    مرّتين، فأنعشه النداء الأول في مكانه ووجده الثاني طازجًا — فمرّ الحجب
    كأنه بلا أثر. الاختبار كان يقيس كائنًا مُعدَّلًا لا الإنعاش.
    """
    from apps.authentication.models import Organization
    from apps.rule_engine.models import AuditRun
    from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
        AuditRunResult,
    )

    org = Organization.objects.create(name="Guard Org", name_ar="حارس")

    def stale_object():
        """كائن على قيم الإنشاء، والقاعدة تحمل غيرها — كما يفعل الأنبوب."""
        run = _run_for(org)
        AuditRun.objects.filter(pk=run.pk).update(
            total_rules=19, risk_score=100, risk_level="critical")
        assert run.total_rules == 0 and run.risk_level == "low"
        return run

    # الحال الصحيح: الغلاف يتجاوز الذاكرة إلى الصفّ.
    assert AuditRunResult.from_audit_run(stale_object()).total_rules == 19

    # العيب يعود: `refresh_from_db` بلا أثر، وكائن جديد لم يُمَسّ.
    monkeypatch.setattr(AuditRun, "refresh_from_db", lambda self, *a, **k: None)
    stale = AuditRunResult.from_audit_run(stale_object())
    assert stale.total_rules == 0 and stale.risk_level == "low", (
        f"حجب الإنعاش لم يُعِد العيب ({stale.total_rules}/{stale.risk_level}) — "
        "فالحارس أعلاه لا يقيس الإنعاش"
    )
