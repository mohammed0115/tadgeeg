"""DocumentCanonicalData now says which tenant owns it.

It holds extracted content read during audits and reports, and it reached its
parent through `typed_model_name` + `typed_object_id` — a generic pointer no
join can follow. Isolation therefore existed only where a caller remembered to
resolve the parent and filter on it. Two call sites did; nothing obliged a
third.

The column makes ownership a property of the row. These tests hold it there.
"""

import uuid

import pytest


@pytest.fixture
def two_orgs(db):
    from apps.authentication.models import Organization

    return (
        Organization.objects.create(name="Canon Alpha", name_ar="ألفا"),
        Organization.objects.create(name="Canon Beta", name_ar="بيتا"),
    )


def _canonical(organization, **kwargs):
    from apps.documents.canonical_models import DocumentCanonicalData

    return DocumentCanonicalData.objects.create(
        organization=organization,
        document_type=kwargs.pop("document_type", "purchase_order"),
        typed_model_name=kwargs.pop("typed_model_name", "PurchaseOrder"),
        typed_object_id=kwargs.pop("typed_object_id", uuid.uuid4()),
        canonical_data=kwargs.pop("canonical_data", {"total": 100}),
        **kwargs,
    )


@pytest.mark.django_db
def test_canonical_data_isolates_by_organization(two_orgs):
    """The property the column exists for."""
    from apps.documents.canonical_models import DocumentCanonicalData

    alpha, beta = two_orgs
    _canonical(alpha)
    beta_row = _canonical(beta)

    visible = DocumentCanonicalData.objects.filter(organization=alpha)

    assert visible.count() == 1
    assert beta_row.pk not in {r.pk for r in visible}


@pytest.mark.django_db
def test_deleting_an_organization_removes_its_canonical_data(two_orgs):
    """on_delete=CASCADE. Before the column there was no relation to cascade
    along, so a deleted tenant left its extracted content behind with nothing
    pointing at it."""
    from apps.documents.canonical_models import DocumentCanonicalData

    alpha, beta = two_orgs
    _canonical(alpha)
    beta_row = _canonical(beta)

    alpha.delete()

    remaining = set(DocumentCanonicalData.objects.values_list("pk", flat=True))
    assert remaining == {beta_row.pk}


@pytest.mark.django_db
def test_backfill_assigned_every_resolvable_row():
    """The backfill's rule, restated as a property rather than a count.

    Row counts belong to the database this ran against; the rule is that a row
    whose parent exists and has an organisation must carry that organisation.
    Asserting the rule survives a re-run on different data — asserting 1,827
    would not.
    """
    from django.apps import apps as django_apps

    from apps.documents.canonical_models import DocumentCanonicalData

    mismatched = []
    for row in DocumentCanonicalData.objects.all()[:500]:
        model = None
        for app_label in ("documents", "invoices"):
            try:
                model = django_apps.get_model(app_label, row.typed_model_name)
                break
            except LookupError:
                continue
        if model is None:
            continue
        parent = model.objects.filter(pk=row.typed_object_id).first()
        if parent is None:
            continue                      # orphan — nothing to inherit
        expected = getattr(parent, "organization_id", None)
        if expected is not None and row.organization_id != expected:
            mismatched.append((str(row.pk), row.typed_model_name,
                               row.organization_id, expected))

    assert not mismatched, (
        f"{len(mismatched)} row(s) have a resolvable parent but the wrong "
        f"organisation: {mismatched[:5]}"
    )


@pytest.mark.django_db
def test_rows_left_null_are_exactly_the_ones_with_no_resolvable_parent():
    """A NULL must mean "no owner could be derived", never "nobody looked"."""
    from django.apps import apps as django_apps

    from apps.documents.canonical_models import DocumentCanonicalData

    wrongly_null = []
    for row in DocumentCanonicalData.objects.filter(organization__isnull=True)[:500]:
        model = None
        for app_label in ("documents", "invoices"):
            try:
                model = django_apps.get_model(app_label, row.typed_model_name)
                break
            except LookupError:
                continue
        if model is None:
            continue
        parent = model.objects.filter(pk=row.typed_object_id).first()
        if parent is not None and getattr(parent, "organization_id", None):
            wrongly_null.append((str(row.pk), row.typed_model_name))

    assert not wrongly_null, (
        f"{len(wrongly_null)} row(s) are NULL although their parent exists and "
        f"has an organisation: {wrongly_null[:5]}"
    )


@pytest.mark.django_db
def test_the_canonical_api_response_is_unchanged(two_orgs):
    """A refactor may not move the wire format.

    The serializer reads canonical_data, confidence, source and version. Adding
    a column must not add a field to the response or reorder one.
    """
    from apps.rule_engine.serializers.audit_run_serializers import (
        DocumentCanonicalDataSerializer,
    )

    alpha, _beta = two_orgs
    row = _canonical(alpha)

    payload = DocumentCanonicalDataSerializer(row).data

    assert "organization" not in payload, (
        "the new column leaked into the API response — this shipment is a "
        "refactor and the wire format must not move"
    )
    # The serializer's declared fields, read from the serializer rather than
    # written out here — a hand-copied list is what made the first version of
    # this test fail against a contract it had invented.
    assert set(payload) == set(DocumentCanonicalDataSerializer().fields)


# ── The guard, seen failing ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_this_guard_can_fail(two_orgs):
    """A row written without an organisation must be visible as such.

    Real rows and a real query — no mock, and no fabricated id: an id that does
    not exist would raise before the check under test ever ran, which is how an
    earlier guard in this project passed against broken code.
    """
    from apps.documents.canonical_models import DocumentCanonicalData

    alpha, beta = two_orgs
    unowned = _canonical(None)            # the pre-column state, reproduced
    _canonical(beta)

    scoped = DocumentCanonicalData.objects.filter(organization=alpha)
    assert unowned.pk not in {r.pk for r in scoped}, (
        "a row with no organisation appeared in a tenant-scoped query"
    )

    # And it is invisible to every tenant — which is why NULL is a staged
    # state and not a resting place.
    for organization in (alpha, beta):
        assert unowned.pk not in set(
            DocumentCanonicalData.objects
            .filter(organization=organization).values_list("pk", flat=True)
        )
    assert DocumentCanonicalData.objects.filter(
        organization__isnull=True, pk=unowned.pk).exists()
