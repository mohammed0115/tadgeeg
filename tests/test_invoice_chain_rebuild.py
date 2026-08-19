"""invoices.0016's constraint cannot build over a forked chain, so 0015a rebuilds it.

The fork is not hypothetical. Measured on a copy of production data on
2026-08-18, while rehearsing the migration batch before deploying it:

    IntegrityError: (1062, "Duplicate entry
      '88bc8c33-fbb0-48cb-963b-62220dc5b2bb-13'
      for key 'invoice_audit_events.uniq_chain_position_invoiceauditevent'")

Nine positions in one organisation's chain held more than one row, and twelve
rows held none. Every collision had the same shape — two events with the *same*
`previous_hash` and different `event_hash`, seconds apart:

    13  processed  20:27:35  prev=0cb1e7e04a  hash=8eea413c3e
    13  uploaded   20:27:44  prev=0cb1e7e04a  hash=cb288bf24b

That is what is planted below: not "two rows at one position", which any
`update()` can produce, but two rows that read the same chain head.

`activity_logs` and `authentication` each got a rebuild before their fork
constraint. `invoices` got the constraint alone, and it was the only chain
table in the database that failed. Without 0015a this deploy puts production
into a restart loop: AddConstraint raises, entrypoint.sh exits under `set -e`,
and `restart: unless-stopped` runs it again.
"""

from importlib import import_module

import pytest
from django.db import IntegrityError, connection

from apps.audit.integrity import GENESIS_HASH, verify_chain
from apps.authentication.models import Organization, User
from apps.invoices.models import Invoice, InvoiceAuditEvent

MIGRATION = "apps.invoices.migrations.0016_chain_partition_and_fork_constraint"
CONSTRAINT_NAME = "uniq_chain_position_invoiceauditevent"


def _rebuild():
    """The migration's own function, driven directly.

    It is handed the live registry, which a *migration* must never do — see
    tests/test_migration_0013_historical_registry.py for what that costs. Here
    the test database is fully migrated, so the two registries describe the
    same columns. The tree-wide ratchet in that file is what keeps 0015a itself
    from reaching for the live registry.
    """
    from django.apps import apps as live_apps

    return lambda: import_module(MIGRATION).rebuild_chains(live_apps, None)


def _constraint():
    return next(
        c for c in InvoiceAuditEvent._meta.constraints if c.name == CONSTRAINT_NAME
    )


def _constraint_exists():
    with connection.cursor() as cursor:
        names = connection.introspection.get_constraints(
            cursor, InvoiceAuditEvent._meta.db_table
        )
    return CONSTRAINT_NAME in names


def _drop_constraint():
    """Take the constraint off the table — and off Meta while doing it.

    SQLite cannot drop a table constraint, so Django rebuilds the table from
    `model._meta`. Leaving the constraint in Meta means the rebuilt table gets
    it straight back, and the call reports success having changed nothing. Two
    earlier versions of this helper did exactly that — first `DROP INDEX`,
    which matched no object because a Meta constraint is compiled into CREATE
    TABLE, then `remove_constraint` with Meta untouched. Both were silent, and
    both were caught only because the planted fork then failed on a constraint
    that was supposed to be gone.

    This is what the migration framework does too: it hands the schema editor a
    historical model built from a state the constraint has been removed from.
    """
    meta = InvoiceAuditEvent._meta
    original = list(meta.constraints)
    target = _constraint()
    meta.constraints = [c for c in original if c.name != CONSTRAINT_NAME]
    try:
        with connection.schema_editor(atomic=False) as editor:
            editor.remove_constraint(InvoiceAuditEvent, target)
    finally:
        meta.constraints = original
    assert not _constraint_exists(), "the constraint survived the drop"


def _clear_remake_leftovers():
    """Remove the scratch table a failed SQLite remake leaves behind.

    SQLite adds a constraint by building `new__<table>`, copying the rows in,
    and swapping. When the copy hits a duplicate — which is the whole point of
    the test below — the exception escapes and the scratch table stays. The
    next remake then dies on "table new__invoice_audit_events already exists",
    and so does the flush at teardown, so one expected failure took out every
    test after it.
    """
    if connection.vendor != "sqlite":
        return
    scratch = connection.ops.quote_name("new__" + InvoiceAuditEvent._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {scratch}")


def _add_constraint():
    """Exactly what 0016's AddConstraint does, against whatever rows are present."""
    try:
        with connection.schema_editor(atomic=False) as editor:
            editor.add_constraint(InvoiceAuditEvent, _constraint())
    except Exception:
        _clear_remake_leftovers()
        raise


@pytest.fixture(autouse=True)
def _constraint_restored(transactional_db):
    """Put the constraint back, whatever the test did to it.

    These tests need the schema editor, and SQLite's refuses to open inside an
    atomic block — so they cannot run in the transaction pytest-django would
    otherwise roll back. That makes the DDL real and persistent, and a test
    that dropped a unique constraint and left it dropped would quietly weaken
    every test that ran after it in the same session.

    Rows are cleared first because restoring cannot be conditional on the data
    being clean: a planted fork is exactly the state that would make the
    restore fail and leave the schema wrong.

    An earlier version of this file emitted `DROP INDEX` instead. It raised
    nothing and did nothing: on SQLite a Meta constraint is compiled into the
    CREATE TABLE statement, not into a separate index, so the drop matched no
    object and the planted fork then failed on the constraint that was still
    there.
    """
    _clear_remake_leftovers()
    yield
    _clear_remake_leftovers()
    InvoiceAuditEvent.objects.all().delete()
    if not _constraint_exists():
        _add_constraint()


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def org():
    return Organization.objects.create(name="Rebuild Org")


@pytest.fixture
def user(org):
    return User.objects.create_user(
        email="rebuild-auditor@test.local",
        full_name="Rebuild Auditor",
        password="x",
        organization=org,
        role=User.Role.ADMIN,
    )


@pytest.fixture
def invoice(org, user):
    return Invoice.objects.create(
        organization=org,
        uploaded_by=user,
        invoice_number="INV-REBUILD-1",
        vendor_name="RebuildVendor",
        total_amount=100,
        original_filename="r.pdf",
    )


@pytest.fixture
def chain(invoice, user):
    """Three linked events, then the measured collision planted on the third."""
    events = [
        InvoiceAuditEvent.objects.create(
            invoice=invoice,
            user=user,
            event_type=event_type,
            description=description,
        )
        for event_type, description in (
            (InvoiceAuditEvent.EventType.UPLOADED, "e1 upload"),
            (InvoiceAuditEvent.EventType.PROCESSED, "e2 process"),
            (InvoiceAuditEvent.EventType.UPLOADED, "e3 upload, late commit"),
        )
    ]
    for event in events:
        event.refresh_from_db()
    return events


def _plant_the_fork(events):
    """Make e3 a sibling of e2: same predecessor, same position, own hash.

    The constraint has to come off first — it exists precisely to make this
    state unreachable, which is the point of planting it.
    """
    e1, e2, e3 = events
    _drop_constraint()
    InvoiceAuditEvent.objects.filter(pk=e3.pk).update(
        chain_position=e2.chain_position,
        previous_hash=e1.event_hash,
    )
    return e1, e2, e3


# ── The planted defect ───────────────────────────────────────────────────────


def test_the_measured_fork_blocks_the_constraint(chain):
    """Without the rebuild, 0016's AddConstraint raises. This is the outage."""
    _plant_the_fork(chain)

    with pytest.raises(IntegrityError):
        _add_constraint()


def test_the_planted_rows_have_the_shape_that_was_measured(chain):
    """A collision produced by two writers, not by an arbitrary renumber."""
    e1, e2, e3 = _plant_the_fork(chain)
    e2.refresh_from_db()
    e3.refresh_from_db()

    assert e2.chain_position == e3.chain_position
    assert e2.previous_hash == e3.previous_hash == e1.event_hash
    assert e2.event_hash != e3.event_hash


# ── The fix ──────────────────────────────────────────────────────────────────


def test_the_rebuild_makes_the_constraint_applicable(chain):
    """Same planted fork, rebuild first: the constraint now builds."""
    _plant_the_fork(chain)

    _rebuild()()
    _add_constraint()  # raises if the rebuild left any collision behind

    positions = list(
        InvoiceAuditEvent.objects.order_by("chain_position")
        .values_list("chain_position", flat=True)
    )
    assert positions == [1, 2, 3]


def test_the_rebuild_loses_no_row(chain, invoice):
    """Positions and hashes change; the recorded facts do not."""
    _plant_the_fork(chain)
    before = sorted(
        InvoiceAuditEvent.objects.values_list("id", "event_type", "description")
    )

    _rebuild()()

    after = sorted(
        InvoiceAuditEvent.objects.values_list("id", "event_type", "description")
    )
    assert after == before


def test_rebuilt_rows_verify(chain, invoice):
    """The baseline the rebuild exists to establish, checked by the real verifier.

    verify_chain recomputes every hash with compute_hash. If 0015a's inlined
    copy of the payload or the hash material had drifted by one byte, this
    fails — which is what keeps the two in step.
    """
    _plant_the_fork(chain)
    assert not verify_chain(
        InvoiceAuditEvent, str(invoice.organization_id)
    ).is_intact, "the planted fork should read as broken before the rebuild"

    _rebuild()()

    report = verify_chain(InvoiceAuditEvent, str(invoice.organization_id))
    assert report.is_intact, f"rebuilt chain does not verify: {report}"


def test_a_row_with_no_position_is_given_one(chain, invoice):
    """The twelve NULL rows measured alongside the collisions."""
    _drop_constraint()
    InvoiceAuditEvent.objects.filter(pk=chain[2].pk).update(chain_position=None)

    _rebuild()()

    assert not InvoiceAuditEvent.objects.filter(chain_position__isnull=True).exists()
    _add_constraint()


# ── Fidelity of the inlined copies ───────────────────────────────────────────


def test_the_inlined_genesis_matches_the_live_one():
    """0015a hand-copies this value; a divergence puts every chain head wrong."""
    assert import_module(MIGRATION).GENESIS_HASH == GENESIS_HASH


def test_the_rebuild_runs_before_the_constraint_inside_one_migration():
    """Read off 0016's own operation list, not off a dependency edge.

    The rebuild used to be a separate 0015a that 0016 depended on. Any graph
    edge making it a parent raises InconsistentMigrationHistory on every
    database that applied 0016 before that file existed, and `run_before`
    builds the identical edge — Django's loader turns both into
    `node_map[child].add_parent(...)`. `migrate` runs the consistency check
    before it would honour `--fake`, so no operator command clears it either.

    Folded into one migration, the ordering is structural: a list cannot be
    reordered by the graph.
    """
    from importlib import import_module

    operations = import_module(MIGRATION).Migration.operations
    names = [
        getattr(op, "code", None).__name__ if hasattr(op, "code")
        else type(op).__name__
        for op in operations
    ]
    assert "rebuild_chains" in names, "the rebuild is gone from 0016"
    assert names.index("rebuild_chains") < names.index("AddConstraint"), (
        "the constraint would build over a chain that has not been rebuilt"
    )
    assert names.index("freeze_partitions") < names.index("rebuild_chains"), (
        "the rebuild reads the partition the freeze writes"
    )
