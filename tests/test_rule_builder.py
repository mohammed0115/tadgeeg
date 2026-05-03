"""
Tests for Phase 2.2 — Custom Rule Builder.

Covers:
  • DSL validator rejects malformed conditions and unknown operators.
  • Evaluator handles all operator categories (comparison, string, list,
    existence) and combinators (all/any/not + nesting).
  • Sandbox API runs a draft rule against a sample of invoices.
  • Publish workflow: only admin/CAO can publish; published rules become
    immutable to PUT.
  • Audit-engine integration: published DSL rules show up in AuditReport.
"""

from __future__ import annotations

import pytest

from apps.audit.models import CustomRuleDefinition
from apps.audit.services.rule_dsl import (
    DSLValidationError, evaluate, sandbox_run, validate_dsl,
)
from apps.authentication.models import Organization, User
from rest_framework.test import APIClient


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def org(db):
    return Organization.objects.create(name="RB Test Org")


@pytest.fixture
def admin(db, org):
    return User.objects.create_user(
        email="admin@rb.test", full_name="Admin", password="x",
        organization=org, role=User.Role.ADMIN,
    )


@pytest.fixture
def junior(db, org):
    return User.objects.create_user(
        email="junior@rb.test", full_name="Junior", password="x",
        organization=org, role=User.Role.JUNIOR_AUDITOR,
    )


@pytest.fixture
def admin_client(admin):
    c = APIClient(); c.force_authenticate(admin); return c


@pytest.fixture
def junior_client(junior):
    c = APIClient(); c.force_authenticate(junior); return c


# ─────────────────────────────────────────────────────────────────────────────
# 1. DSL validation
# ─────────────────────────────────────────────────────────────────────────────

def test_validate_accepts_simple_dsl():
    validate_dsl({
        "when": {"field": "total_amount", "op": ">", "value": 100},
        "then": {"action": "flag", "severity": "high", "message": "x"},
    })


def test_validate_rejects_missing_when_or_then():
    with pytest.raises(DSLValidationError):
        validate_dsl({"when": {"field": "x", "op": "==", "value": 1}})


def test_validate_rejects_unknown_op():
    with pytest.raises(DSLValidationError, match="Unknown operator"):
        validate_dsl({
            "when": {"field": "total_amount", "op": "crashes", "value": 1},
            "then": {"action": "flag", "severity": "high"},
        })


def test_validate_rejects_invalid_regex():
    with pytest.raises(DSLValidationError, match="regex"):
        validate_dsl({
            "when": {"field": "vendor_name", "op": "regex", "value": "[unclosed"},
            "then": {"action": "flag", "severity": "high"},
        })


def test_validate_rejects_mixed_combinators():
    with pytest.raises(DSLValidationError, match="combinator"):
        validate_dsl({
            "when": {
                "all": [{"field": "x", "op": "==", "value": 1}],
                "any": [{"field": "x", "op": "==", "value": 1}],
            },
            "then": {"action": "flag", "severity": "high"},
        })


def test_validate_rejects_empty_combinator_list():
    with pytest.raises(DSLValidationError, match="non-empty"):
        validate_dsl({
            "when": {"all": []},
            "then": {"action": "flag", "severity": "high"},
        })


# ─────────────────────────────────────────────────────────────────────────────
# 2. Evaluator
# ─────────────────────────────────────────────────────────────────────────────

def test_eval_comparison_operators():
    doc = {"total_amount": 5000}
    for op, val, expected in [(">", 4000, True), ("<", 4000, False),
                              (">=", 5000, True), ("<=", 5000, True),
                              ("==", 5000, True), ("!=", 5000, False)]:
        dsl = {"when": {"field": "total_amount", "op": op, "value": val},
               "then": {"action": "flag", "severity": "high"}}
        assert evaluate(dsl, doc).triggered is expected, f"op={op}"


def test_eval_string_operators():
    doc = {"vendor_name": "ACME Trading Co."}
    cases = [
        ("contains", "ACME", True),
        ("not_contains", "Foo", True),
        ("starts_with", "ACME", True),
        ("ends_with", "Co.", True),
        ("regex", r"^ACME .+ Co\.$", True),
        ("regex", r"^XYZ", False),
    ]
    for op, val, expected in cases:
        dsl = {"when": {"field": "vendor_name", "op": op, "value": val},
               "then": {"action": "flag", "severity": "high"}}
        assert evaluate(dsl, doc).triggered is expected, f"{op} {val}"


def test_eval_existence_operators():
    doc = {"vendor_vat_number": "", "currency": "SAR"}
    dsl_empty = {"when": {"field": "vendor_vat_number", "op": "is_empty"},
                 "then": {"action": "flag", "severity": "high"}}
    dsl_set   = {"when": {"field": "currency", "op": "is_set"},
                 "then": {"action": "flag", "severity": "high"}}
    assert evaluate(dsl_empty, doc).triggered is True
    assert evaluate(dsl_set, doc).triggered is True


def test_eval_list_operators():
    doc = {"currency": "USD"}
    dsl_in = {"when": {"field": "currency", "op": "in", "value": ["USD", "EUR"]},
              "then": {"action": "flag", "severity": "high"}}
    dsl_not_in = {"when": {"field": "currency", "op": "not_in", "value": ["SAR"]},
                  "then": {"action": "flag", "severity": "high"}}
    assert evaluate(dsl_in, doc).triggered is True
    assert evaluate(dsl_not_in, doc).triggered is True


def test_eval_nested_combinators():
    doc = {"total_amount": 200000, "vendor_vat_number": "", "currency": "SAR"}
    dsl = {
        "when": {
            "all": [
                {"field": "total_amount", "op": ">", "value": 100000},
                {"any": [
                    {"field": "vendor_vat_number", "op": "is_empty"},
                    {"field": "currency", "op": "!=", "value": "SAR"},
                ]},
            ],
        },
        "then": {"action": "flag", "severity": "high",
                 "message": "Large invoice with missing VAT or non-SAR currency"},
    }
    res = evaluate(dsl, doc)
    assert res.triggered is True
    assert res.message.startswith("Large invoice")


def test_eval_not_combinator():
    doc = {"is_duplicate": False}
    dsl = {
        "when": {"not": {"field": "is_duplicate", "op": "==", "value": True}},
        "then": {"action": "flag", "severity": "low"},
    }
    assert evaluate(dsl, doc).triggered is True


def test_eval_dotted_path_lookup():
    """Field paths support nested dicts and list indexing."""
    doc = {"line_items": [{"amount": 999}, {"amount": 1500}]}
    dsl = {
        "when": {"field": "line_items.1.amount", "op": ">", "value": 1000},
        "then": {"action": "flag", "severity": "medium"},
    }
    assert evaluate(dsl, doc).triggered is True


def test_eval_invalid_dsl_returns_unfired_result():
    """A malformed DSL must NOT raise from the evaluator — it returns triggered=False."""
    res = evaluate({"when": {"field": "x", "op": "BAD"}, "then": {}}, {"x": 1})
    assert res.triggered is False
    assert "invalid" in res.explanation.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Sandbox
# ─────────────────────────────────────────────────────────────────────────────

def test_sandbox_run_counts_triggers():
    sample = [
        {"id": "1", "invoice_number": "A1", "total_amount": 100},
        {"id": "2", "invoice_number": "A2", "total_amount": 5000},
        {"id": "3", "invoice_number": "A3", "total_amount": 9999},
    ]
    dsl = {
        "when": {"field": "total_amount", "op": ">", "value": 1000},
        "then": {"action": "flag", "severity": "high"},
    }
    res = sandbox_run(dsl, sample)
    assert res["ok"] is True
    assert res["triggered_count"] == 2
    assert res["sample_size"] == 3
    triggered_ids = {r["id"] for r in res["rows"] if r["triggered"]}
    assert triggered_ids == {"2", "3"}


def test_sandbox_run_returns_error_on_invalid_dsl():
    res = sandbox_run({"when": {"all": []}, "then": {}}, [])
    assert res["ok"] is False
    assert "non-empty" in res["error"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. API + publish workflow
# ─────────────────────────────────────────────────────────────────────────────

def test_api_create_and_publish_admin(db, admin_client, admin):
    # Create a draft.
    res = admin_client.post("/api/v1/audit/rule-builder/", {
        "name": "Big invoices",
        "description": "Flag invoices over SAR 100k",
        "severity": "high",
        "condition_type": "dsl",
        "expression_dsl": {
            "when": {"field": "total_amount", "op": ">", "value": 100000},
            "then": {"action": "flag", "severity": "high",
                     "message": "Large invoice"},
        },
    }, format="json")
    assert res.status_code == 201, res.content
    rule_id = res.data["id"]
    assert res.data["status"] == "draft"

    # Publish.
    res2 = admin_client.post(f"/api/v1/audit/rule-builder/{rule_id}/publish/")
    assert res2.status_code == 200, res2.content
    assert res2.data["status"] == "published"
    assert res2.data["published_at"]


def test_api_publish_requires_admin(db, junior_client, admin, org):
    rule = CustomRuleDefinition.objects.create(
        organization=org, name="x", condition_type="dsl",
        expression_dsl={"when": {"field": "total_amount", "op": ">", "value": 1},
                        "then": {"action": "flag", "severity": "high"}},
        created_by=admin,
    )
    res = junior_client.post(f"/api/v1/audit/rule-builder/{rule.id}/publish/")
    assert res.status_code == 403


def test_api_published_rule_cannot_be_edited(db, admin_client, admin, org):
    rule = CustomRuleDefinition.objects.create(
        organization=org, name="locked", condition_type="dsl",
        status=CustomRuleDefinition.Status.PUBLISHED,
        expression_dsl={"when": {"field": "total_amount", "op": ">", "value": 1},
                        "then": {"action": "flag", "severity": "high"}},
        created_by=admin,
    )
    res = admin_client.put(
        f"/api/v1/audit/rule-builder/{rule.id}/",
        {"name": "altered"}, format="json",
    )
    assert res.status_code == 409


def test_api_invalid_dsl_rejected_at_create(db, admin_client):
    res = admin_client.post("/api/v1/audit/rule-builder/", {
        "name": "bad", "condition_type": "dsl",
        "expression_dsl": {"when": {"field": "x", "op": "FOO", "value": 1},
                           "then": {"action": "flag", "severity": "high"}},
    }, format="json")
    assert res.status_code == 400
    assert "Unknown operator" in res.data["error"] or "invalid" in res.data["error"].lower()


def test_api_dsl_schema_endpoint(db, admin_client):
    res = admin_client.get("/api/v1/audit/rule-builder/dsl-schema/")
    assert res.status_code == 200
    assert "fields" in res.data
    assert "operators" in res.data
    assert "actions" in res.data


# ─────────────────────────────────────────────────────────────────────────────
# 5. Audit engine integration
# ─────────────────────────────────────────────────────────────────────────────

def test_published_dsl_rule_runs_inside_audit_engine(db, org):
    """A PUBLISHED rule should appear in AuditReport.rule_results."""
    from apps.audit.audit_engine import AuditEngine
    CustomRuleDefinition.objects.create(
        organization=org, name="High-value", condition_type="dsl",
        status=CustomRuleDefinition.Status.PUBLISHED,
        expression_dsl={
            "when": {"field": "total_amount", "op": ">", "value": 50000},
            "then": {"action": "flag", "severity": "high",
                     "message": "Big spend"},
        },
        severity="high",
    )

    engine = AuditEngine(organization_id=org.id)
    report = engine.evaluate(
        document={
            "document_type": "invoice",
            "document_number": "TEST-1",
            "vendor_name": "Vendor X",
            "total_amount": 75000,
            "currency": "SAR",
        }, invoice_id=None,
    )

    custom = [r for r in report.rule_results if r.rule_id.startswith("CUSTOM-")]
    assert len(custom) == 1
    assert custom[0].result.value == "FAILED"
    assert "Big spend" in custom[0].explanation


def test_draft_rule_does_not_run_inside_audit_engine(db, org):
    """Drafts must NOT leak into the audit pipeline — only PUBLISHED rules run."""
    from apps.audit.audit_engine import AuditEngine
    CustomRuleDefinition.objects.create(
        organization=org, name="Draft only", condition_type="dsl",
        status=CustomRuleDefinition.Status.DRAFT,  # ← key
        expression_dsl={
            "when": {"field": "total_amount", "op": ">", "value": 0},
            "then": {"action": "flag", "severity": "low"},
        },
    )

    engine = AuditEngine(organization_id=org.id)
    report = engine.evaluate(
        document={"document_type": "invoice", "total_amount": 1000},
        invoice_id=None,
    )
    custom = [r for r in report.rule_results if r.rule_id.startswith("CUSTOM-")]
    assert custom == []
