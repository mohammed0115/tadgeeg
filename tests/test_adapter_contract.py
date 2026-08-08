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
