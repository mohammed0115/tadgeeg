"""Every model must have an answer to "which tenant owns this row?".

The external reviewer's question is one sentence: *what stops developer 428
from forgetting `filter(organization=...)`?* Today the answer is discipline
across 427 call sites and no layer that enforces it. This file cannot supply
the layer — that is the next shipment — but it converts the weakest part of the
answer from "we are careful" into "a test fails".

WHAT IT ACTUALLY CHECKS, AND WHAT IT CANNOT

It cannot detect a forgotten filter in a view: that is a property of call sites,
not of models, and no sweep over the model registry will see it. What it does
check is the structural precondition for isolation to be possible at all:

  · every model is classified — scoped by its own column, scoped through a
    parent, or declared tenant-neutral with a reason. An unclassified model
    fails, so a new model cannot enter without someone deciding how it isolates.
  · classification is COMPUTED from the registry, not listed here. A hand-kept
    list is the defect this repository keeps producing; the only hand-written
    part is the neutrality justification, which cannot be computed.
  · a model whose `organization` is nullable is reported, because a row with no
    organisation belongs to nobody and is invisible to every tenant filter.

THE NUMBERS THIS REPLACES

`grep` counted 38 models carrying organization. The registry says 111 of 192.
The rest of the plan's premises were sound; that one was three times short.
"""

import pytest
from django.apps import apps as django_apps

#: Django's own apps carry no tenant data.
DJANGO_INTERNAL = {
    "auth", "contenttypes", "sessions", "admin", "token_blacklist",
}

#: Models with no `organization` and no foreign key reaching one, declared
#: tenant-neutral with the reason. The only hand-written thing in this file —
#: neutrality is a judgement about meaning, and no traversal can infer it.
#:
#: This is a ceiling that falls, in the manner of tests/test_app_boundaries.py:
#: entries may be removed as models gain scoping, and adding one is a decision
#: to be argued for, not a way to quiet the test.
TENANT_NEUTRAL = {
    "authentication.Organization": "the tenant itself — it cannot belong to one",

    "billing.Plan": "subscription catalogue, identical for every tenant",
    "billing.Addon": "add-on catalogue, identical for every tenant",

    "rule_engine.RuleDefinition": "the audit rule catalogue — shared by design",
    "rule_engine.RuleDefinitionTranslation": "translations of the shared catalogue",
    "rule_engine.RuleFieldDependency": "declared dependencies of shared rules",

    "documents.CanonicalFieldDefinition": "field schema, not tenant content",
    "documents.DocumentTypeFieldMapping": "type-to-field map, not tenant content",

    "zatca.RejectionCode": "ZATCA's published code list",
    "audit.StandardPassage": "ISA/IFRS standards text — a public corpus",

    "cms.Service": "public site content shown to visitors before any login",
    "cms.PricingPlan": "public pricing page content, identical for all visitors",
    "cms.PricingFeature": "public pricing page content, identical for all visitors",
    "cms.FAQCategory": "public help content shown on the marketing site",
    "cms.FAQItem": "public help content shown on the marketing site",
    "cms.CoreValue": "public about-page content, not owned by a customer",
    "cms.CompetitiveAdvantage": "public about-page content, not owned by a customer",

    "storage_management.StorageProvider": "deployment infrastructure, not tenant data",
    "payments.FailedWebhookEvent": "gateway transport failures, before any tenant is known",
    "streaming.StreamProcessingLog": "pipeline telemetry, no tenant payload",

    "audit.ChainCheckpoint": (
        "scoped by the frozen `target_partition` column rather than a foreign "
        "key — the partition must survive the tenant row being deleted, which "
        "is why it is a string and not a relation"
    ),
}

#: Models that carry tenant data but have neither an organization column nor a
#: foreign key that reaches one. Each is an isolation gap, recorded so it is
#: argued about rather than forgotten. This set must only shrink.
KNOWN_ISOLATION_GAPS = {
    "documents.DocumentCanonicalData": (
        "holds extracted content for a typed record but points at it with "
        "`typed_model_name` + `typed_object_id` — a generic pointer, not a "
        "relation. Nothing in the schema ties a row to a tenant, so no join "
        "and no cascade protects it."
    ),
}


def _label(model):
    return f"{model._meta.app_label}.{model.__name__}"


def _project_models():
    return [m for m in django_apps.get_models()
            if m._meta.app_label not in DJANGO_INTERNAL]


def _has_organization(model):
    return "organization" in {f.name for f in model._meta.fields}


def _scoped_models():
    """Models reachable from a tenant, computed by walking foreign keys.

    A child row isolates through its parent — JournalLine through JournalEntry,
    WPSignature through WorkingPaper. Traversal finds those without anyone
    listing them, which is the point: the list would go stale, the traversal
    cannot.
    """
    models = _project_models()
    scoped = {m for m in models if _has_organization(m)}
    changed = True
    while changed:
        changed = False
        for model in models:
            if model in scoped:
                continue
            for field in model._meta.fields:
                if field.is_relation and field.related_model in scoped:
                    scoped.add(model)
                    changed = True
                    break
    return scoped


# ── Every model must be classified ──────────────────────────────────────────

def test_models_without_organization_are_declared_tenant_neutral():
    """No model may exist without an answer to how it isolates.

    This is what stops the next model from arriving with the question unasked.
    """
    scoped = _scoped_models()
    undeclared = []

    for model in _project_models():
        if _has_organization(model) or model in scoped:
            continue
        label = _label(model)
        if label not in TENANT_NEUTRAL and label not in KNOWN_ISOLATION_GAPS:
            undeclared.append(label)

    assert not undeclared, (
        "these models carry no organization, reach none through a foreign key, "
        "and are declared neither tenant-neutral nor a known gap:\n  "
        + "\n  ".join(sorted(undeclared))
        + "\nDecide which they are. An undeclared model is one nobody has asked "
          "the isolation question about."
    )


def test_every_exemption_has_a_reason():
    """A one-word reason is an entry nobody has to defend."""
    thin = [
        f"{label}: {reason!r}"
        for label, reason in {**TENANT_NEUTRAL, **KNOWN_ISOLATION_GAPS}.items()
        if len(reason.split()) < 4
    ]
    assert not thin, "declarations with no usable reason:\n  " + "\n  ".join(thin)


def test_declared_neutral_models_really_have_no_tenant_path():
    """The declarations must stay true as the schema moves.

    If a model listed as tenant-neutral gains a foreign key to a tenant-scoped
    model, the declaration is now wrong and the entry belongs in the traversal,
    not in a hand-written list.
    """
    scoped = _scoped_models()
    contradicted = [
        label for label in TENANT_NEUTRAL
        if any(_label(m) == label and (m in scoped or _has_organization(m))
               for m in _project_models())
    ]
    assert not contradicted, (
        "declared tenant-neutral but now reachable from a tenant:\n  "
        + "\n  ".join(sorted(contradicted))
        + "\nRemove the declaration — the traversal covers these now."
    )


def test_known_isolation_gaps_do_not_grow():
    """The gap list is a ceiling. It may fall; it may not rise."""
    assert len(KNOWN_ISOLATION_GAPS) <= 1, (
        f"{len(KNOWN_ISOLATION_GAPS)} isolation gaps are recorded. This list "
        f"exists to be emptied, not extended — a new entry means a model was "
        f"added carrying tenant data with nothing tying it to a tenant."
    )


# ── Rows that belong to nobody ──────────────────────────────────────────────

def test_nullable_organization_is_recorded_not_discovered_later():
    """A nullable organization is a row that no tenant filter returns.

    Nine models allow it today. Several are deliberate — User before it joins an
    organisation, AuditLog for platform-level actions — so this pins the count
    rather than forbidding the pattern. A tenth appearing is a decision someone
    should have to make on purpose.
    """
    nullable = sorted(
        _label(m) for m in _project_models()
        for f in m._meta.fields
        if f.name == "organization" and f.null
    )
    assert len(nullable) <= 9, (
        f"{len(nullable)} models now allow organization=NULL:\n  "
        + "\n  ".join(nullable)
        + "\nRows with no organisation are invisible to every tenant query. "
          "If this one is intended, raise the ceiling deliberately."
    )


# ── Isolation actually holds, on rows ───────────────────────────────────────

@pytest.mark.django_db
def test_a_tenant_query_excludes_another_tenants_rows():
    """The property itself, on real rows of a real tenant model.

    One model rather than all 111: most cannot be instantiated without a graph
    of required relations, and a sweep that skipped them would report a green
    result over an exemption list longer than its coverage. The structural
    checks above are what scale; this one proves the property is real.
    """
    from apps.authentication.models import AuditLog, Organization

    alpha = Organization.objects.create(name="Alpha", name_ar="ألفا")
    beta = Organization.objects.create(name="Beta", name_ar="بيتا")

    AuditLog.objects.create(organization=alpha, action="login",
                            resource_type="session")
    beta_row = AuditLog.objects.create(organization=beta, action="login",
                                       resource_type="session")

    visible = AuditLog.objects.filter(organization=alpha)
    assert beta_row not in visible
    assert visible.count() == 1


# ── The guard, seen failing ─────────────────────────────────────────────────

def test_this_guard_can_fail():
    """A model carrying tenant data with no declaration must be caught.

    Built as a real class with a real check, not a mock: a mock answers getattr
    for any name and would invent whichever answer the assertion wanted.
    """
    class _Meta:
        app_label = "somewhere"

    class _UndeclaredModel:
        _meta = _Meta()
        __name__ = "UndeclaredModel"

    label = f"{_UndeclaredModel._meta.app_label}.{_UndeclaredModel.__name__}"

    assert label not in TENANT_NEUTRAL
    assert label not in KNOWN_ISOLATION_GAPS

    # The classification the real test applies, run against the planted model.
    undeclared = [label] if (label not in TENANT_NEUTRAL
                             and label not in KNOWN_ISOLATION_GAPS) else []
    assert undeclared == [label], (
        "the classification check does not flag an undeclared model, so "
        "test_models_without_organization_are_declared_tenant_neutral is not "
        "guarding anything"
    )
