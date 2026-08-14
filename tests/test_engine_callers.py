"""الخطوة ٣ — من يستدعي أي محرّك، محسوبًا لا مكتوبًا.

الموضع: tests/test_engine_callers.py

**الجذر الذي يعالجه هذا الملف.** ترحيل المحرّكات القديمة نُفِّذ بإخلاص مقابل
قائمة `Callers:` مكتوبة بيد في رأس `legacy_audit_adapter.py`:

    1. apps.audit.audit_engine.AuditEngine / run_audit
         Callers:   apps/audit/tasks.py (audit_high_risk_documents)

وكانت القائمة تحمل مستدعيًا واحدًا من أربعة. فأفلت `core/services/pipeline.py`
— لا بإهمال، بل لأنه **لم يكن في القائمة**. سطر grep واحد كان سيجده.

فالقاعدة التي يفرضها هذا الملف: **لا قائمة مستدعين يدوية لما يمكن حسابه.**

يتبع نمط `tests/test_app_boundaries.py`: سقف يتناقص ولا يرتفع، وكل استثناء
يحمل سببه المكتوب.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from django.conf import settings


# ═════════════════════════════════════════════════════════════════════════════
# ١. المحرّك القديم AuditEngine — يجب أن يبلغ صفرًا ثم يُحذف الملف
# ═════════════════════════════════════════════════════════════════════════════

#: كل مستدعٍ إنتاجي لـ`apps.audit.audit_engine` مع سببه.
#: هذا سقف: يُحذف منه مدخل عند ترحيله، ولا يُضاف إليه مدخل جديد أبدًا.
#: عند خلوّه ⇒ الخطوة ٥ من docs/UNIFICATION_PLAN.md (حذف الملف) صارت آمنة.
_LEGACY_ENGINE_CALLERS: dict[str, str] = {
    "apps/invoices/services/processor.py": (
        "مخرج طوارئ محميّ بـ USE_NEW_RULE_ENGINE — الاستيراد داخل الفرع "
        "`if not USE_NEW_RULE_ENGINE`. يبقى حتى تُحذف الراية في الخطوة ٦."
    ),
}

#: المسموح لها دائمًا: الجسر يستورد ما يجسره، والملف يستورد نفسه.
_LEGACY_ENGINE_ALLOWED = (
    "apps/rule_engine/services/compatibility/legacy_audit_adapter.py",
    "apps/audit/audit_engine.py",
)


# ═════════════════════════════════════════════════════════════════════════════
# ٢. أنبوب V1 — سقف يتناقص حتى يبقى compat.py وحده
# ═════════════════════════════════════════════════════════════════════════════

#: مستوردو `executors.audit_pipeline` مباشرةً، أي المتجاوزون لمفتاح
#: AUDIT_ENGINE_VERSION. لا يبقى هنا إلا استثناء أداة الجاهزية ومسار تقرير
#: GAAP القديم؛ كل مسار منتج يمر عبر `run_audit_compat`.
#: يُحذف مدخل عند تحويله أو حذفه، ولا يُضاف مدخل جديد.
_V1_DIRECT_CALLERS: dict[str, str] = {
    "apps/reports/services/gaap_service.py": (
        "فرع `persist=True` **بلا مستدعٍ واحد في المستودع**: الخمسة الذين "
        "ينادون `evaluate_gaap_rules_for_invoice` كلهم على الافتراضي "
        "`persist=False`، وثلاثة منهم يستوردون دالة أخرى بالاسم نفسه من "
        "`apps/auditing/accounting_rules/services.py` لا تملك المعامل أصلًا. "
        "⇒ كود ميت **يُحذف لا يُحوَّل** — وتحويله يُبقي في هذا السقف مدخلًا "
        "يُقرأ لاحقًا كأنه مسار حيّ. بند مسجَّل."
    ),
    "apps/rule_engine/management/commands/bootstrap_readiness_window.py": (
        "**ليس مستدعي تدقيق.** يستعمل الأنبوب كصندوق أدوات: يستخرج "
        "`selector` و`aggregator`، وينادي ثلاثة أعضاء خاصّة "
        "(`_execute_single_rule` · `_count_statuses` · `_upsert_risk_summary`)، "
        "ويبني `AuditRun` بنفسه على حمولة اصطناعية لا يقابلها صفّ. "
        "`run_audit_compat` يتوقّع مفتاح سجل مُطبوع، فلا بديل هنا. "
        "**لا يُحوَّل ولا يُحذف من السقف** — هو فعلًا يستورد V1."
    ),
}

#: `compat.py` هو الموضع الوحيد المسموح له باستيراد V1 نهائيًا: مهمته أن يختار
#: بين النسختين. إن اختفى منه الاستيراد، فقد اختفى مسار التراجع كله.
_V1_ALLOWED = ("apps/rule_engine/pipeline/v2/compat.py",)


# ═════════════════════════════════════════════════════════════════════════════
# أدوات
# ═════════════════════════════════════════════════════════════════════════════

_SKIP_DIRS = {"migrations", "node_modules", ".git", "tests", "__pycache__"}


def _production_python_files() -> list[Path]:
    base = Path(settings.BASE_DIR)
    out: list[Path] = []
    for root in ("apps", "core", "finai_backend"):
        for path in (base / root).rglob("*.py"):
            parts = set(path.parts)
            if parts & _SKIP_DIRS:
                continue
            if path.name.startswith("test_") or path.name == "conftest.py":
                continue
            out.append(path)
    return out


def _imports_module(path: Path, needle: str) -> bool:
    """هل يستورد الملف الوحدة المطلوبة — بالـAST لا بالنصّ.

    البحث النصّي يلتقط الوحدة في تعليق أو في docstring، وهذا بالضبط ما جعل حارس
    السلاسل اليدوية في commit 8102cf1 عاجزًا عن الفشل: كان يفحص وجود سلسلة
    نصّية لا استيرادًا فعليًا.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == needle or node.module.startswith(needle + "."):
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == needle or alias.name.startswith(needle + "."):
                    return True
    return False


def _actual_callers(module: str, allowed: tuple[str, ...]) -> set[str]:
    base = Path(settings.BASE_DIR)
    found = set()
    for path in _production_python_files():
        rel = str(path.relative_to(base))
        if rel in allowed:
            continue
        if _imports_module(path, module):
            found.add(rel)
    return found


# ═════════════════════════════════════════════════════════════════════════════
# الاختبارات
# ═════════════════════════════════════════════════════════════════════════════


def test_legacy_engine_callers_match_the_recorded_ceiling():
    """مستدعو `apps.audit.audit_engine` هم المسجّلون بالضبط — لا أكثر.

    مستدعٍ جديد يفشل هذا الاختبار: المحرّك في طريقه إلى الحذف، وإضافة مستدعٍ
    إليه تعمل في الاتجاه المعاكس.
    """
    actual = _actual_callers("apps.audit.audit_engine", _LEGACY_ENGINE_ALLOWED)
    recorded = set(_LEGACY_ENGINE_CALLERS)

    unrecorded = actual - recorded
    assert not unrecorded, (
        f"مستدعون جدد لـ AuditEngine القديم: {sorted(unrecorded)}\n"
        "هذا المحرّك في طريقه إلى الحذف (docs/UNIFICATION_PLAN.md الخطوة ٥). "
        "استعمل `run_audit_compat` أو `LegacyAuditEngineAdapter` بدلًا منه."
    )

    stale = recorded - actual
    assert not stale, (
        f"مستدعون مسجّلون ولم يبقوا: {sorted(stale)}\n"
        "احذفهم من _LEGACY_ENGINE_CALLERS. سقف أعلى من الواقع يشتري صامتًا "
        "مكانًا لعودة التراجع — وهذا سبب وجود هذا الاختبار."
    )


def test_v1_pipeline_direct_callers_match_the_recorded_ceiling():
    """مستوردو V1 مباشرةً هم المسجّلون بالضبط.

    كل مدخل هنا هو موضع يتجاوز مفتاح AUDIT_ENGINE_VERSION، أي موضع لا يستطيع
    التراجع بتغيير إعداد. العدد ينزل ولا يصعد.
    """
    actual = _actual_callers("apps.rule_engine.executors.audit_pipeline", _V1_ALLOWED)
    recorded = set(_V1_DIRECT_CALLERS)

    unrecorded = actual - recorded
    assert not unrecorded, (
        f"مستوردون جدد لأنبوب V1 مباشرةً: {sorted(unrecorded)}\n"
        "الاستيراد المباشر يتجاوز AUDIT_ENGINE_VERSION، فيُعطِّل مسار التراجع. "
        "استعمل `apps.rule_engine.pipeline.v2.compat.run_audit_compat`."
    )

    stale = recorded - actual
    assert not stale, (
        f"مسجّلون ولم يبقوا: {sorted(stale)} — احذفهم من _V1_DIRECT_CALLERS."
    )


def test_every_recorded_caller_carries_a_reason():
    """كل استثناء يحمل سببه مكتوبًا.

    قائمة استثناءات بلا أسباب تصير قائمة أبدية: لا أحد يعرف أيّ مدخل يمكن
    حذفه. وهذا هو نمط `test_app_boundaries.py` القائم في هذه المجموعة.
    """
    for name, table in (
        ("_LEGACY_ENGINE_CALLERS", _LEGACY_ENGINE_CALLERS),
        ("_V1_DIRECT_CALLERS", _V1_DIRECT_CALLERS),
    ):
        for rel, reason in table.items():
            assert reason and len(reason.strip()) > 20, (
                f"{name}['{rel}'] بلا سبب مفهوم. اكتب لماذا يبقى ومتى يُحذف."
            )


def test_audit_engine_version_is_defined_explicitly():
    """المفتاح معرَّف في الإعدادات لا مخبوءًا كافتراضي في الشيفرة.

    ⚠️ يفشل الآن، وهذا مقصود — الخطوة ٧ من الخطة. `compat.py` يعلن أن تبديل
    النسخة «يحتاج تغيير إعداد فقط»، والإعداد غير معرَّف إطلاقًا، فالقيمة تأتي
    من افتراضي مكتوب في الشيفرة. القيمة المعرَّفة صراحةً أفضل من افتراضي
    مخبوء: أول من يقرأ الإعدادات يرى ما يعمل.
    """
    assert hasattr(settings, "AUDIT_ENGINE_VERSION"), (
        "AUDIT_ENGINE_VERSION غير معرَّف في الإعدادات. أضف إلى "
        "finai_backend/settings_canonical.py:\n"
        '    AUDIT_ENGINE_VERSION = os.environ.get("AUDIT_ENGINE_VERSION", "v2")'
    )
    assert settings.AUDIT_ENGINE_VERSION in ("v1", "v2", "shadow")


def test_this_guard_can_fail(tmp_path):
    """⚠️ إلزامي — يُزرع ملف مخالف ويُتأكَّد من التقاطه.

    درس commit 3d29066: الحارس السابق تخطّى أي `models.py` يحتوي السلسلة
    "HashChainMixin"، والـcommit الذي أدخله وضع تلك السلسلة في الملف الوحيد
    المخالف — فأبلغ عن صفر مخالفات منذ لحظة كتابته.
    """
    offender = tmp_path / "planted_offender.py"
    offender.write_text(
        "from apps.audit.audit_engine import AuditEngine\n"
        "engine = AuditEngine(organization_id=1)\n",
        encoding="utf-8",
    )
    assert _imports_module(offender, "apps.audit.audit_engine"), (
        "المُكتشِف لا يلتقط استيرادًا صريحًا — فالاختبارات أعلاه تمرّ بلا أن "
        "تفحص شيئًا."
    )

    innocent = tmp_path / "innocent.py"
    innocent.write_text(
        '"""يذكر apps.audit.audit_engine في التوثيق فقط."""\n'
        "# from apps.audit.audit_engine import AuditEngine  ← معلَّق\n"
        "VALUE = 1\n",
        encoding="utf-8",
    )
    assert not _imports_module(innocent, "apps.audit.audit_engine"), (
        "المُكتشِف يلتقط ذِكرًا نصّيًا لا استيرادًا. حارس يُطلق إنذارات كاذبة "
        "يُسكَت بعد أول واحد."
    )
