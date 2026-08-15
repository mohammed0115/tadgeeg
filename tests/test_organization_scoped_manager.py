"""OrganizationScopedManager, exercised on a model that already has it available.

The manager is not attached to anything yet — that is the next shipment — so
this tests it the way it will be used: constructed against an existing
tenant-scoped model's table rather than against a throwaway model, which would
need a migration this shipment is not permitted to create.
"""

import pytest

from core.managers import OrganizationScopedQuerySet


@pytest.fixture
def two_orgs(db):
    from apps.authentication.models import Organization

    return (
        Organization.objects.create(name="Scoped Alpha", name_ar="ألفا"),
        Organization.objects.create(name="Scoped Beta", name_ar="بيتا"),
    )


def _scoped(model):
    """The model's rows through the scoped queryset, without attaching it."""
    return OrganizationScopedQuerySet(model=model, using=model.objects.db)


@pytest.mark.django_db
def test_for_organization_returns_only_that_organizations_rows(two_orgs):
    from apps.authentication.models import AuditLog

    alpha, beta = two_orgs
    AuditLog.objects.create(organization=alpha, action="login",
                            resource_type="session")
    AuditLog.objects.create(organization=alpha, action="logout",
                            resource_type="session")
    beta_row = AuditLog.objects.create(organization=beta, action="login",
                                       resource_type="session")

    rows = _scoped(AuditLog).for_organization(alpha)

    assert rows.count() == 2
    assert beta_row.pk not in {r.pk for r in rows}


@pytest.mark.django_db
def test_it_accepts_a_primary_key_as_well_as_an_instance(two_orgs):
    """Call sites hold both. A manager that refuses one gets bypassed."""
    from apps.authentication.models import AuditLog

    alpha, _beta = two_orgs
    AuditLog.objects.create(organization=alpha, action="login",
                            resource_type="session")

    by_instance = _scoped(AuditLog).for_organization(alpha).count()
    by_pk = _scoped(AuditLog).for_organization(alpha.pk).count()

    assert by_instance == by_pk == 1


@pytest.mark.django_db
def test_none_is_refused_rather_than_returning_everything(two_orgs):
    """`filter(organization=None)` would quietly return nothing; passing None
    to a scoping helper usually means a variable was empty upstream. Either way
    the caller should hear about it."""
    from apps.authentication.models import AuditLog

    with pytest.raises(ValueError, match="every tenant"):
        _scoped(AuditLog).for_organization(None)


def test_the_manager_is_not_attached_to_any_model_yet():
    """This shipment builds the tool and measures the gap; it does not wire it.

    Attaching a default manager to 111 models changes the meaning of 427 call
    sites at once, including the ones that read across tenants on purpose. If
    this test starts failing, the wiring shipment has begun and its acceptance
    test is the golden master, not this file.
    """
    from django.apps import apps as django_apps

    from core.managers import OrganizationScopedManager

    attached = [
        f"{m._meta.app_label}.{m.__name__}"
        for m in django_apps.get_models()
        if isinstance(m._default_manager, OrganizationScopedManager)
    ]
    assert not attached, (
        f"OrganizationScopedManager is now the default manager on {attached}. "
        f"That is the wiring shipment — it needs the golden master as its gate."
    )
