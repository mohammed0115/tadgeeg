"""A manager that makes tenant scoping explicit at the query, not the call site.

Isolation in this codebase rests on 427 hand-written `filter(organization=...)`
calls and nothing that enforces them. The reviewer's question is what stops the
428th from being forgotten, and the honest answer today is nothing structural.

This is the first half of an answer. The second half — attaching it to models —
is deliberately not done here, for the reason in the class docstring.
"""

from __future__ import annotations

from django.db import models


class OrganizationScopedQuerySet(models.QuerySet):
    """A queryset that can narrow itself to one tenant."""

    def for_organization(self, organization):
        """Rows belonging to `organization`.

        Accepts the instance or its primary key, because call sites hold both
        and a manager that forces the caller to convert invites the caller to
        skip the manager.
        """
        if organization is None:
            raise ValueError(
                "for_organization(None) would return every tenant's rows. If "
                "you want the unscoped queryset, ask for it by name — silence "
                "is how cross-tenant reads happen."
            )
        key = getattr(organization, "pk", organization)
        return self.filter(organization_id=key)


class OrganizationScopedManager(models.Manager.from_queryset(OrganizationScopedQuerySet)):
    """Adds `.for_organization(org)` and changes nothing else.

    WHY get_queryset IS NOT OVERRIDDEN

    The obvious version of this class filters by a thread-local current tenant
    inside get_queryset, so unscoped reads become impossible. That is the right
    destination and the wrong first step.

    Attaching a filtering default manager to 111 models alters the meaning of
    427 existing call sites in one commit. Every one of them already filters
    explicitly, so the result would be either a redundant filter — harmless —
    or a silently narrowed queryset in the places that deliberately read across
    tenants: platform-admin views, the billing reconciliation job, the nightly
    chain verifier. Those are not distinguishable from a defect by reading the
    diff, and this project's standard for a refactor is that the output does
    not change at all.

    So this manager is additive. `.for_organization(org)` is a way to say the
    thing explicitly and be read as saying it; the enforcement layer comes after
    the call sites have been surveyed, in a shipment whose acceptance test is
    the golden master rather than a hope.

    NOT ATTACHED TO ANY MODEL YET

    Nothing imports this. That is intentional for this shipment: the sweep in
    tests/test_tenant_isolation_sweep.py measures which models would need it
    and what their current state is, and attaching before reading that is how
    one ends up migrating the wrong 38 of 111.
    """
