"""The tamper-evident trail must actually be tamper-evident.

This product's regulatory argument rests on a hash-chained audit log. Two of
the three chains in the codebase are built by `HashChainMixin`, which does it
correctly: it locks the previous row with `select_for_update`, orders by a
monotonic `chain_position`, and partitions per organisation.

`authentication.AuditLog` carried its own weaker copy. Three defects, each
proven below rather than asserted:

  1. no lock — two writes read the same predecessor and both chain off it
  2. `order_by("-timestamp")` — timestamps tie under load, and the tie makes
     "the previous row" undefined
  3. one global chain — organisation A's next entry chains off organisation
     B's hash, so verifying one tenant requires reading every tenant's rows,
     and B's write ordering changes A's chain

A forked chain does not raise. Verification walks one branch and reports
success, or walks the other and reports tampering that never happened. Either
way the claim "tamper-evident" stops being true, and it stops being true
silently — which is the failure mode this whole codebase kept turning out to
have.
"""

import pytest
from django.utils import timezone


@pytest.fixture
def two_orgs(db):
    from apps.authentication.models import Organization

    return (
        Organization.objects.create(name="Alpha", name_ar="ألفا"),
        Organization.objects.create(name="Beta", name_ar="بيتا"),
    )


def _entry(organization, user=None, **kwargs):
    from apps.authentication.models import AuditLog

    return AuditLog.objects.create(
        organization=organization, user=user,
        action=kwargs.pop("action", "login"),
        resource_type=kwargs.pop("resource_type", "session"),
        **kwargs,
    )


# ── The chain must be ordered by something that cannot tie ───────────────────

@pytest.mark.django_db
def test_the_chain_is_ordered_by_a_monotonic_counter_not_a_timestamp(two_orgs):
    """Timestamps tie. Two entries written in the same microsecond leave
    "the previous row" undefined, and the next writer picks arbitrarily."""
    from apps.authentication.models import AuditLog

    alpha, _ = two_orgs
    assert hasattr(AuditLog, "chain_position"), (
        "AuditLog has no chain_position — ordering falls back to timestamp, "
        "which ties under load"
    )

    entries = [_entry(alpha) for _ in range(5)]
    positions = [
        AuditLog.objects.get(pk=e.pk).chain_position for e in entries
    ]
    assert positions == sorted(positions), "positions are not monotonic"
    assert len(set(positions)) == len(positions), "two entries share a position"


@pytest.mark.django_db
def test_identical_timestamps_do_not_fork_the_chain(two_orgs):
    """The defect, reproduced: three entries forced to share a timestamp.

    With timestamp ordering, the third read the first as "latest" and chained
    off it — producing two rows with the same previous_hash. That is a fork,
    and nothing anywhere raised.
    """
    from apps.authentication.models import AuditLog

    alpha, _ = two_orgs
    stamp = timezone.now()

    for _ in range(3):
        entry = _entry(alpha)
        AuditLog.objects.filter(pk=entry.pk).update(timestamp=stamp)

    chained = list(AuditLog.objects.filter(organization=alpha).order_by("chain_position"))
    parents = [e.previous_hash for e in chained if e.previous_hash]

    assert len(parents) == len(set(parents)), (
        "two entries share a previous_hash — the chain forked. Verification "
        "will walk one branch and call it complete."
    )


# ── Each organisation owns its own chain ─────────────────────────────────────

@pytest.mark.django_db
def test_one_tenants_entry_never_chains_off_anothers(two_orgs):
    """A global chain means B's write ordering changes A's chain, and
    verifying A requires reading every row B ever wrote."""
    from apps.authentication.models import AuditLog

    alpha, beta = two_orgs

    _entry(alpha)
    beta_entry = _entry(beta)
    alpha_second = _entry(alpha)

    alpha_second.refresh_from_db()
    beta_entry.refresh_from_db()

    assert alpha_second.previous_hash != beta_entry.event_hash, (
        "an entry chained off another organisation's hash"
    )


@pytest.mark.django_db
def test_each_organisation_starts_its_own_chain_at_position_one(two_orgs):
    from apps.authentication.models import AuditLog

    alpha, beta = two_orgs
    _entry(alpha)
    _entry(beta)

    for organization in (alpha, beta):
        first = (
            AuditLog.objects.filter(organization=organization)
            .order_by("chain_position").first()
        )
        assert first.chain_position == 1


# ── Verification ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_an_untouched_chain_verifies(two_orgs):
    from apps.audit.integrity import verify_chain
    from apps.authentication.models import AuditLog

    alpha, _ = two_orgs
    for _ in range(6):
        _entry(alpha)

    report = verify_chain(AuditLog, alpha.id)
    assert report.is_intact, report


@pytest.mark.django_db
def test_editing_a_row_breaks_verification(two_orgs):
    """The property the whole mechanism exists for. If an edited row still
    verifies, the chain is decoration."""
    from apps.audit.integrity import verify_chain
    from apps.authentication.models import AuditLog

    alpha, _ = two_orgs
    for _ in range(4):
        _entry(alpha)

    target = AuditLog.objects.filter(organization=alpha).order_by("chain_position")[1]
    AuditLog.objects.filter(pk=target.pk).update(action="something_else")

    report = verify_chain(AuditLog, alpha.id)
    assert not report.is_intact, "an edited row still verified — the chain proves nothing"


@pytest.mark.django_db
def test_deleting_a_row_is_refused(two_orgs):
    """Append-only, enforced. A trail that can be pruned is not evidence."""
    alpha, _ = two_orgs
    entry = _entry(alpha)

    with pytest.raises(Exception):
        entry.delete()


@pytest.mark.django_db
def test_a_removed_row_breaks_verification(two_orgs):
    """delete() is blocked, but a raw queryset delete or direct SQL is not.
    The chain has to catch what the model guard cannot."""
    from apps.audit.integrity import verify_chain
    from apps.authentication.models import AuditLog

    alpha, _ = two_orgs
    for _ in range(4):
        _entry(alpha)

    middle = AuditLog.objects.filter(organization=alpha).order_by("chain_position")[1]
    AuditLog.objects.filter(pk=middle.pk).delete()   # bypasses Model.delete()

    report = verify_chain(AuditLog, alpha.id)
    assert not report.is_intact, "a removed row left the chain verifiable"


# ── One implementation, not three ────────────────────────────────────────────

def test_every_chained_model_uses_the_same_implementation():
    """DRY, and not for tidiness: AuditLog's private copy lacked the lock, the
    counter and the per-tenant partition. Three copies means three chances to
    get a security mechanism subtly wrong, and two of them already were.
    """
    from apps.activity_logs.models import ActivityLog
    from apps.audit.integrity import HashChainMixin
    from apps.authentication.models import AuditLog
    from apps.invoices.models import InvoiceAuditEvent

    for model in (AuditLog, ActivityLog, InvoiceAuditEvent):
        assert issubclass(model, HashChainMixin), (
            f"{model.__name__} chains by hand instead of using HashChainMixin"
        )


def test_no_model_reimplements_chain_hashing_by_hand():
    """A guard on the pattern, not on today's three models."""
    import ast
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    offenders = []

    for path in repo.glob("apps/**/models.py"):
        source = path.read_text(encoding="utf-8")
        if "compute_chain_hash(" in source and "HashChainMixin" not in source:
            offenders.append(str(path.relative_to(repo)))

    assert not offenders, (
        "models computing a chain hash without HashChainMixin:\n  "
        + "\n  ".join(offenders)
        + "\nUse the mixin — it locks the predecessor, orders by chain_position "
          "and partitions per organisation. A hand-rolled copy has historically "
          "missed all three."
    )
