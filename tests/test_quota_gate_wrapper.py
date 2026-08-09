"""The billing gate must wrap the audit entry point without swallowing it.

`install_gate()` replaces `compat.run_audit_compat` with a wrapper that
reserves quota and then calls the original. The original was captured at
install time and stored on `_gated._original`. It was never read: the wrapper's
body re-imported `run_audit_compat` at call time, which by then resolved to the
wrapper itself, so every call through the patched entry point recursed until
the stack ran out.

WHY 3,936 TESTS PASSED OVER IT

The existing coverage (tests/test_qa_fixes.py, tests/test_post_qa_hardening.py)
calls `run_audit_with_quota` directly. That is the wrapped function, not the
wrapper — the patched module attribute is exactly what those tests never touch,
and the patch is what creates the defect. A test can exercise a function
thoroughly and still never exercise the way production reaches it.

So the first test below goes through `compat.run_audit_compat` after the gate
is installed, which is the path production uses and the only one that fails.
"""

import pytest


@pytest.fixture
def gate_installed():
    """Ensure the gate is installed, as it is in production via AppConfig.ready."""
    from apps.billing import quota_gate

    quota_gate.install_gate()
    import apps.rule_engine.pipeline.v2.compat as compat_mod
    return compat_mod


# ── The defect ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_calling_the_patched_entrypoint_does_not_recurse(gate_installed, monkeypatch):
    """The path production takes: the module attribute, after patching.

    The document and quota lookups are stubbed deliberately. An earlier version
    of this test passed a non-existent document id and asserted "no
    RecursionError" — and it passed against the broken code, because
    _resolve_document_and_org raises first and the call never reaches
    _original, which is where the recursion lives. A guard that stops short of
    the defect is not a guard; verified by reverting the fix and watching this
    fail.
    """
    from apps.billing import quota_gate

    compat_mod = gate_installed
    reached = {"pipeline": False}

    class _Svc:
        def can_audit(self, *a, **k):
            return {"allowed": True, "reason": "", "remaining": 10,
                    "subscription": None}

        def reserve_invoice_audit(self, *a, **k):
            pass

        def consume_invoice_audit(self, *a, **k):
            pass

        def release_invoice_audit(self, *a, **k):
            pass

    def _fake_pipeline(**kwargs):
        reached["pipeline"] = True
        return object()

    monkeypatch.setattr(quota_gate, "QuotaService", _Svc)
    monkeypatch.setattr(
        quota_gate, "_resolve_document_and_org",
        lambda d, o: (object(), object()),
    )
    monkeypatch.setattr(quota_gate, "_already_billed", lambda org, doc: False)
    # Inject at the gate's own record of the original. Patching
    # compat.run_audit_compat instead would replace the wrapper itself, and the
    # call would never enter the gate — which is the thing under test.
    monkeypatch.setattr(quota_gate, "_ORIGINAL_RUN_AUDIT", _fake_pipeline)

    compat_mod.run_audit_compat(
        document_id="d", document_type="sales_invoice", organization_id="o",
    )

    assert reached["pipeline"], (
        "the wrapper never reached the pipeline — it resolved the entry point "
        "to itself instead of the original it saved"
    )


def test_the_wrapper_exposes_the_original_it_replaced(gate_installed):
    """The attribute the fix depends on. If install_gate stops setting it, the
    fallback silently starts calling the wrapper again."""
    compat_mod = gate_installed

    gated = compat_mod.run_audit_compat
    assert getattr(gated, "_billing_gated", False), "gate is not installed"
    original = getattr(gated, "_original", None)
    assert original is not None, "install_gate no longer stores _original"
    assert original is not gated, "_original points at the wrapper itself"


# ── The guard, seen failing ──────────────────────────────────────────────────

def test_this_guard_can_fail(monkeypatch):
    """Rebuild the defect deliberately and confirm the guard catches it.

    A guard nobody has watched fail is not a guard. This patches the module
    with a wrapper written the original, broken way — re-importing the entry
    point at call time — and asserts that a RecursionError is what comes out.
    If this ever stops raising, the test above is no longer proving anything.
    """
    import apps.rule_engine.pipeline.v2.compat as compat_mod

    real = compat_mod.run_audit_compat

    def _broken_wrapper(*args, **kwargs):
        # The bug, verbatim: resolve the entry point at call time, by which
        # point it is this very function.
        from apps.rule_engine.pipeline.v2.compat import run_audit_compat as _o
        return _o(*args, **kwargs)

    monkeypatch.setattr(compat_mod, "run_audit_compat", _broken_wrapper)

    with pytest.raises(RecursionError):
        compat_mod.run_audit_compat(
            document_id="x", document_type="sales_invoice", organization_id="y",
        )

    # monkeypatch restores it, but assert rather than trust.
    monkeypatch.undo()
    assert compat_mod.run_audit_compat is real


# ── The fix must not have disabled billing ───────────────────────────────────

@pytest.mark.django_db
def test_quota_is_consumed_exactly_once(monkeypatch):
    """Routing around the recursion by skipping the gate would also "fix" it.

    The reservation must still happen, and exactly once per audited document —
    a wrapper that no longer bills is a worse defect than the one being
    removed, and a quieter one.
    """
    from apps.billing import quota_gate

    calls = {"reserve": 0, "consume": 0, "pipeline": 0}

    class _Svc:
        def can_audit(self, *a, **k):
            # Matches QuotaService.can_audit's contract — a decision dict, not
            # a bool. The gate reads decision["allowed"].
            return {"allowed": True, "reason": "", "remaining": 10,
                    "subscription": None}

        def reserve_invoice_audit(self, *a, **k):
            calls["reserve"] += 1

        def consume_invoice_audit(self, *a, **k):
            calls["consume"] += 1

        def release_invoice_audit(self, *a, **k):
            pass

    def _fake_pipeline(**kwargs):
        calls["pipeline"] += 1
        return object()

    monkeypatch.setattr(quota_gate, "QuotaService", _Svc)
    monkeypatch.setattr(
        quota_gate, "_resolve_document_and_org",
        lambda d, o: (object(), object()),
    )
    monkeypatch.setattr(quota_gate, "_already_billed", lambda org, doc: False)

    quota_gate.install_gate()
    monkeypatch.setattr(quota_gate, "_ORIGINAL_RUN_AUDIT", _fake_pipeline)

    quota_gate.run_audit_with_quota(
        document_id="d", document_type="sales_invoice", organization_id="o",
    )

    assert calls["pipeline"] == 1, "the pipeline was not run once"
    assert calls["reserve"] == 1, (
        f"quota reserved {calls['reserve']} times — billing must happen exactly once"
    )
