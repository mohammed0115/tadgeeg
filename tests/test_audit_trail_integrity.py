"""The tamper-evident trail must actually be tamper-evident.

This product's regulatory argument rests on a hash-chained audit log. Every
chained model is built by `HashChainMixin`, which orders by a monotonic
`chain_position`, partitions per organisation, and refuses duplicate positions
at the database.

`authentication.AuditLog` carried its own weaker copy. Three defects, each
proven below rather than asserted:

  1. no serialisation — two writes read the same predecessor and both chain
     off it
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

**On how #1 is prevented.** It was first fixed with a `select_for_update` on
the chain head, which did not work: Django sends `pre_save` before `save_base`
opens its write context, so on any caller not already inside `atomic()` the
lock's own transaction committed — releasing the row — before the INSERT. The
lock covered the read alone. Extending it across the insert was the obvious
repair and the wrong one; long-held chain locks are what produced this
codebase's MySQL deadlocks on the upload path.

Correctness now rests on a `UniqueConstraint` over
`(chain_partition, chain_position)`, with the losing writer retrying. That
makes a fork impossible rather than unlikely, holds no lock — and, because a
constraint is enforced identically on MySQL and SQLite while
`select_for_update` is a no-op on the latter, it is the reason the concurrency
tests below can exist at all. Under the old design nothing in this suite could
tell a working lock from a deleted one.

The last section covers retention, where tamper-evidence and policy pull
against each other: rows must be deleted after seven years, and verification
reports the first gap it finds.
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
    """Append-only, enforced. A trail that can be pruned is not evidence.

    `ValueError`, not a bare `Exception`: the loose version passed on any
    failure at all, including an AttributeError from a typo in this test, so it
    could not distinguish "deletion was refused" from "the test is broken".
    """
    alpha, _ = two_orgs
    entry = _entry(alpha)

    with pytest.raises(ValueError, match="append-only"):
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


# ── Concurrency: the property the whole design turns on ──────────────────────

def _append_waiting_out_sqlite(write, attempts=40, pause=0.05):
    """Run `write`, waiting out SQLite's table-level write lock.

    SQLite allows one writer at a time and raises OperationalError("database
    table is locked") rather than queueing, which MySQL — the production
    backend — does not do. That is a property of the test transport, not of
    the thing under test: the chain-head *read* still interleaves freely, so
    two threads genuinely can select the same head and race for the position.
    Waiting here reproduces the queueing MySQL gives for free, and leaves the
    actual race intact.

    Nothing about the chain's correctness is retried here — that retry lives in
    HashChainMixin.save() and is driven by IntegrityError, not by this.
    """
    import time

    from django.db import OperationalError

    for attempt in range(attempts):
        try:
            return write()
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == attempts - 1:
                raise
            time.sleep(pause)

@pytest.mark.django_db(transaction=True)
def test_two_concurrent_appends_cannot_take_the_same_position():
    """Real threads, real connections — the test that could not exist before.

    The old design relied on `select_for_update`, which SQLite does not
    implement, so nothing in this suite could tell a working lock from a
    deleted one. Correctness now rests on a unique constraint, which both
    backends enforce identically, so the guarantee is finally checkable here.

    Note this test would still pass if it merely never raced. What makes it
    meaningful is the assertion below: positions must be *distinct*, which is
    exactly what a fork violates.
    """
    import threading

    from django.db import connections

    from apps.authentication.models import AuditLog, Organization

    org = Organization.objects.create(name="Race", name_ar="سباق")
    barrier = threading.Barrier(6)
    errors = []

    def append():
        try:
            barrier.wait(timeout=10)      # release all writers together
            _append_waiting_out_sqlite(
                lambda: AuditLog.objects.create(
                    organization=org, action="login", resource_type="session",
                )
            )
        except Exception as exc:          # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=append) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"concurrent appends raised: {errors}"

    positions = list(
        AuditLog.objects.filter(organization=org)
        .values_list("chain_position", flat=True)
    )
    assert len(positions) == 6, f"lost a write: {positions}"
    assert len(set(positions)) == 6, (
        f"two rows share a chain position — the chain forked: {sorted(positions)}"
    )
    assert sorted(positions) == [1, 2, 3, 4, 5, 6]


@pytest.mark.django_db(transaction=True)
def test_a_chain_built_concurrently_still_verifies():
    """Distinct positions are not enough — the hashes must link up too."""
    import threading

    from django.db import connections

    from apps.audit.integrity import verify_chain
    from apps.authentication.models import AuditLog, Organization

    org = Organization.objects.create(name="Race2", name_ar="سباق٢")
    barrier = threading.Barrier(5)

    def append():
        try:
            barrier.wait(timeout=10)
            _append_waiting_out_sqlite(
                lambda: AuditLog.objects.create(
                    organization=org, action="login", resource_type="session",
                )
            )
        finally:
            connections.close_all()

    threads = [threading.Thread(target=append) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    report = verify_chain(AuditLog, org.id)
    assert report.is_intact, report.to_dict()


@pytest.mark.django_db
def test_a_writer_that_loses_the_position_race_retries_and_succeeds(two_orgs, monkeypatch):
    """The retry path, forced — because thread scheduling is not a test.

    The threaded cases above can pass without ever colliding: SQLite serialises
    writers behind a table lock, so the interleaving that produces a duplicate
    position is rare there and absent from most runs. A test that only *might*
    exercise the mechanism is not evidence it works.

    So this stages the collision exactly. The writer computes its position, a
    competitor commits that same position before the insert lands, and the
    insert must then fail on the constraint, recompute against the new head,
    and land on the next position — losing nothing.

    Delete the UniqueConstraint and this test fails: without it the competing
    insert succeeds and two rows share a position.
    """
    from apps.audit import integrity, signals
    from apps.authentication.models import AuditLog

    alpha, _ = two_orgs
    _entry(alpha)                                  # position 1
    _entry(alpha)                                  # position 2

    original = integrity.assign_chain_fields
    calls = {"n": 0}

    def collide_once(instance):
        """First attempt claims a position that is already taken.

        Staged this way rather than by inserting a competing row mid-save: the
        retry runs inside a savepoint, so a competitor created there is rolled
        back along with the failed insert, and the second attempt then finds
        the old head and succeeds without ever proving anything.
        """
        calls["n"] += 1
        original(instance)
        if calls["n"] == 1:
            instance.chain_position = 2            # already taken

    # signals.py imported the symbol directly, so patch it there.
    monkeypatch.setattr(signals, "assign_chain_fields", collide_once)

    loser = _entry(alpha)

    assert calls["n"] >= 2, (
        f"the insert never retried — it was attempted {calls['n']} time(s), so "
        f"either the constraint did not fire or the error was not recognised"
    )

    positions = sorted(
        AuditLog.objects.filter(organization=alpha)
        .values_list("chain_position", flat=True)
    )
    assert positions == [1, 2, 3], f"retry did not resolve the race: {positions}"
    assert loser.chain_position == 3, (
        f"the losing writer kept the position it lost: {loser.chain_position}"
    )

    # And the chain it produced must still verify end to end.
    from apps.audit.integrity import verify_chain
    assert verify_chain(AuditLog, alpha.id).is_intact


@pytest.mark.django_db
def test_a_duplicate_position_is_refused_by_the_database(two_orgs):
    """The constraint itself, asserted directly.

    If this ever stops raising, every concurrency guarantee above is void —
    which is why it is tested separately from the threaded cases rather than
    inferred from them.
    """
    from django.db import IntegrityError

    from apps.authentication.models import AuditLog

    alpha, _ = two_orgs
    first = _entry(alpha)
    second = _entry(alpha)

    with pytest.raises(IntegrityError):
        AuditLog.objects.filter(pk=second.pk).update(
            chain_position=first.chain_position
        )


# ── Deleting a user or a tenant is not tampering ─────────────────────────────

@pytest.mark.django_db
def test_deleting_the_actor_does_not_break_the_chain(two_orgs, django_user_model):
    """A person leaving the firm is a routine event, not evidence of tampering.

    `user` is on_delete=SET_NULL and the hash commits to who acted, so reading
    the FK meant an ordinary deletion silently invalidated every row that
    person appeared in.
    """
    from apps.audit.integrity import verify_chain
    from apps.authentication.models import AuditLog

    alpha, _ = two_orgs
    user = django_user_model.objects.create_user(
        username="leaver", email="leaver@example.com", password="x",
    )
    for _ in range(3):
        _entry(alpha, user=user)

    assert verify_chain(AuditLog, alpha.id).is_intact

    user.delete()

    report = verify_chain(AuditLog, alpha.id)
    assert report.is_intact, (
        "deleting a user reported tampering that never happened: "
        f"{report.to_dict()}"
    )


@pytest.mark.django_db
def test_deleting_a_tenant_does_not_move_its_rows_into_the_platform_chain(two_orgs):
    """organization is on_delete=SET_NULL. When the live FK was the partition
    key, deleting a tenant swept its rows into the organization-is-NULL chain
    carrying their old positions — colliding with the platform chain and
    invalidating their hashes at the same time."""
    from apps.audit.integrity import verify_chain
    from apps.authentication.models import AuditLog

    alpha, beta = two_orgs
    for _ in range(3):
        _entry(alpha)
    for _ in range(2):
        _entry(beta)

    alpha_id = alpha.id
    alpha.delete()

    # The rows keep the partition they were hashed under.
    report = verify_chain(AuditLog, alpha_id)
    assert report.rows_checked == 3, (
        "rows left their own chain when the tenant was deleted"
    )
    assert report.is_intact, report.to_dict()
    assert verify_chain(AuditLog, beta.id).is_intact


# ── One implementation, not three ────────────────────────────────────────────

def test_every_chained_model_uses_the_same_implementation():
    """DRY, and not for tidiness: AuditLog's private copy lacked the lock, the
    counter and the per-tenant partition. Three copies means three chances to
    get a security mechanism subtly wrong, and two of them already were.
    """
    from apps.activity_logs.models import ActivityLog, EvidenceAccess
    from apps.audit.integrity import HashChainMixin
    from apps.audit.models import WorkingPaper
    from apps.authentication.models import AuditLog
    from apps.invoices.models import InvoiceAuditEvent
    from apps.ledger.models import JournalEntry

    for model in (AuditLog, ActivityLog, EvidenceAccess,
                  InvoiceAuditEvent, JournalEntry, WorkingPaper):
        assert issubclass(model, HashChainMixin), (
            f"{model.__name__} chains by hand instead of using HashChainMixin"
        )


def test_every_chained_model_refuses_duplicate_positions():
    """The constraint is the fork prevention, so its absence is the defect.

    A model can inherit the mixin and still be forkable if nobody declared the
    constraint — these classes define their own Meta, so they do not inherit
    the abstract parent's.
    """
    from apps.activity_logs.models import ActivityLog, EvidenceAccess
    from apps.audit.models import WorkingPaper
    from apps.authentication.models import AuditLog
    from apps.invoices.models import InvoiceAuditEvent
    from apps.ledger.models import JournalEntry

    for model in (AuditLog, ActivityLog, EvidenceAccess,
                  InvoiceAuditEvent, JournalEntry, WorkingPaper):
        pairs = {
            tuple(c.fields) for c in model._meta.constraints
            if hasattr(c, "fields")
        }
        assert ("chain_partition", "chain_position") in pairs, (
            f"{model.__name__} has no unique constraint on "
            f"(chain_partition, chain_position) — its chain can still fork"
        )


def test_no_model_reimplements_chain_hashing_by_hand():
    """A guard on the pattern, not on today's models — and one that can fail.

    The first version of this test asked whether the *file* contained the
    string "HashChainMixin" and skipped it if so. Every models.py with at least
    one converted model was therefore exempt no matter what else it held, and
    the commit that introduced this guard also converted ActivityLog — putting
    "HashChainMixin" into the one file that still had a hand-rolled chain
    (EvidenceAccess). The guard reported zero offenders from the moment it was
    written, and would have kept doing so while the defect it named sat three
    hundred lines below.

    So the question is now asked per class, via the AST: does this class define
    its own hash-chaining method while not inheriting the mixin?
    """
    import ast
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    offenders = []

    #: Method names that mean "this class rolls its own chain".
    HAND_ROLLED = {"_compute_chain_hash", "compute_chain_hash", "_payload_for_hash"}

    for path in sorted(repo.glob("apps/**/models.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {
                base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                for base in node.bases
            }
            if "HashChainMixin" in bases:
                continue
            methods = {
                child.name for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if methods & HAND_ROLLED:
                offenders.append(
                    f"{path.relative_to(repo)}::{node.name} "
                    f"defines {sorted(methods & HAND_ROLLED)}"
                )

    assert not offenders, (
        "classes computing a chain hash without inheriting HashChainMixin:\n  "
        + "\n  ".join(offenders)
        + "\nUse the mixin. It freezes the partition, refuses duplicate "
          "positions at the database, and retries the loser — a hand-rolled "
          "copy has historically missed all of that."
    )


def test_the_guard_actually_catches_a_hand_rolled_chain(tmp_path):
    """The guard above is only worth having if it can fail. Plant an offender
    and confirm the same logic finds it — the previous version could not.
    """
    import ast

    planted = tmp_path / "models.py"
    planted.write_text(
        "from django.db import models\n"
        "class SneakyLog(models.Model):\n"
        "    def _compute_chain_hash(self):\n"
        "        return 'nope'\n",
        encoding="utf-8",
    )

    HAND_ROLLED = {"_compute_chain_hash", "compute_chain_hash", "_payload_for_hash"}
    found = []
    tree = ast.parse(planted.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {
            base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
            for base in node.bases
        }
        if "HashChainMixin" in bases:
            continue
        methods = {
            child.name for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if methods & HAND_ROLLED:
            found.append(node.name)

    assert found == ["SneakyLog"], "the guard cannot see a hand-rolled chain"


# ── Retention vs tamper-evidence ─────────────────────────────────────────────

@pytest.mark.django_db
def test_purging_an_expired_prefix_does_not_report_tampering(two_orgs):
    """The conflict this whole mechanism exists for.

    Seven-year retention requires deleting old rows. verify_chain reports the
    first gap it finds. Before checkpoints those two facts meant the first
    successful retention run would make the trail report tampering every night
    thereafter — for doing exactly what policy demands.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.audit.integrity import verify_chain
    from apps.authentication.models import AuditLog
    from apps.authentication.tasks import prune_audit_logs

    alpha, _ = two_orgs
    for _ in range(6):
        _entry(alpha)

    # Age the first three past their retention window.
    old = timezone.now() - timedelta(days=1)
    expired = list(
        AuditLog.objects.filter(organization=alpha).order_by("chain_position")[:3]
    )
    AuditLog.objects.filter(pk__in=[e.pk for e in expired]).update(retain_until=old)
    AuditLog.objects.filter(organization=alpha).exclude(
        pk__in=[e.pk for e in expired]
    ).update(retain_until=timezone.now() + timedelta(days=365))

    result = prune_audit_logs()

    assert result["deleted"] == 3, result
    assert AuditLog.objects.filter(organization=alpha).count() == 3

    report = verify_chain(AuditLog, alpha.id)
    assert report.is_intact, (
        f"retention purge reported tampering it did not commit: {report.to_dict()}"
    )


@pytest.mark.django_db
def test_a_checkpoint_records_what_it_removed(two_orgs):
    from datetime import timedelta

    from django.utils import timezone

    from apps.audit.integrity import retire_chain_prefix
    from apps.audit.models import ChainCheckpoint
    from apps.authentication.models import AuditLog

    alpha, _ = two_orgs
    for _ in range(5):
        _entry(alpha)

    third = AuditLog.objects.filter(organization=alpha).order_by("chain_position")[2]
    expected_head = third.event_hash

    checkpoint = retire_chain_prefix(AuditLog, str(alpha.id), 3)

    assert checkpoint.rows_removed == 3
    assert checkpoint.up_to_position == 3
    assert checkpoint.head_hash == expected_head
    assert checkpoint.target_model == "AuditLog"
    # The anchor is itself chained, so forging one means forging its chain.
    assert checkpoint.event_hash
    assert ChainCheckpoint.objects.count() == 1


@pytest.mark.django_db
def test_deleting_a_row_beyond_the_checkpoint_is_still_caught(two_orgs):
    """A checkpoint must excuse only what it actually covers. If it blanket-
    suppressed gap detection, retention would become a laundering channel."""
    from apps.audit.integrity import retire_chain_prefix, verify_chain
    from apps.authentication.models import AuditLog

    alpha, _ = two_orgs
    for _ in range(6):
        _entry(alpha)

    retire_chain_prefix(AuditLog, str(alpha.id), 2)
    assert verify_chain(AuditLog, alpha.id).is_intact

    # Now remove a row the checkpoint does not cover.
    victim = AuditLog.objects.filter(organization=alpha).order_by("chain_position")[1]
    AuditLog.objects.filter(pk=victim.pk).delete()

    report = verify_chain(AuditLog, alpha.id)
    assert not report.is_intact, "a deletion past the checkpoint went unreported"


@pytest.mark.django_db
def test_a_checkpoint_cannot_be_deleted(two_orgs):
    from apps.audit.integrity import retire_chain_prefix
    from apps.authentication.models import AuditLog

    alpha, _ = two_orgs
    for _ in range(3):
        _entry(alpha)
    checkpoint = retire_chain_prefix(AuditLog, str(alpha.id), 2)

    with pytest.raises(ValueError, match="cannot be deleted"):
        checkpoint.delete()


@pytest.mark.django_db
def test_retention_leaves_an_unexpired_row_and_everything_after_it(two_orgs):
    """Only a contiguous expired prefix is retired. A gap in the middle cannot
    be anchored, so those rows must survive until the prefix ahead of them has
    expired too."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.audit.integrity import verify_chain
    from apps.authentication.models import AuditLog
    from apps.authentication.tasks import prune_audit_logs

    alpha, _ = two_orgs
    for _ in range(5):
        _entry(alpha)

    rows = list(AuditLog.objects.filter(organization=alpha).order_by("chain_position"))
    past   = timezone.now() - timedelta(days=1)
    future = timezone.now() + timedelta(days=365)

    # Positions 1, 2 and 4 expired — but 3 has not, so only 1-2 may go.
    AuditLog.objects.filter(pk__in=[rows[0].pk, rows[1].pk, rows[3].pk]).update(retain_until=past)
    AuditLog.objects.filter(pk__in=[rows[2].pk, rows[4].pk]).update(retain_until=future)

    result = prune_audit_logs()

    assert result["deleted"] == 2, f"retired a non-contiguous set: {result}"
    surviving = set(
        AuditLog.objects.filter(organization=alpha)
        .values_list("chain_position", flat=True)
    )
    assert surviving == {3, 4, 5}
    assert verify_chain(AuditLog, alpha.id).is_intact
