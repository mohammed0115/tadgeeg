"""A data migration must read models from the registry it is handed, not the live one.

`documents.0013_canonical_data_organization` resolved each canonical row's parent
through `django.apps.apps` — the registry describing the models as they are
defined *today*. Django hands every RunPython a second, historical registry for
exactly this reason: it describes the models as the database has them at that
point in the plan, and it is the only one whose columns are guaranteed to exist.

Measured on the dev host, 2026-08-17, mid-deploy:

    Applying documents.0013_canonical_data_organization...
    MySQLdb.OperationalError:
        (1054, "Unknown column 'invoices.audit_document_id' in 'field list'")

`audit_document_id` is added by `invoices.0017_invoice_audit_document`, and that
migration *depends on* 0013 — so 0013 always runs first and the column is always
absent when the backfill runs. The live `Invoice` model names it in every SELECT
it generates. The failure is structural, not a race.

What made it expensive is what happened next. `AddField` had already run, and
MySQL commits DDL, so the column existed while the migration stayed unrecorded.
Every restart replayed `AddField` and died on (1060, "Duplicate column name
'organization_id'") — a crash loop under `restart: unless-stopped`, with the
original 1054 scrolled out of the log ring. Two environments were left in that
state before the cause was found.

Live never reached it: the rehearsal on a copy of live data is where it fired.
"""

import uuid

import pytest
from django.apps import apps as live_apps
from django.db.migrations.loader import MigrationLoader

MIGRATION = ("documents", "0013_canonical_data_organization")
ADDS_THE_COLUMN = ("invoices", "0017_invoice_audit_document")
LATE_FIELD = "audit_document"


def _loader() -> MigrationLoader:
    return MigrationLoader(None, ignore_no_migrations=True)


def _backfill():
    """The function under test, imported from the migration itself."""
    migration = _loader().disk_migrations[MIGRATION]
    from django.db.migrations.operations.special import RunPython

    for operation in migration.operations:
        if isinstance(operation, RunPython):
            return operation.code
    raise AssertionError("0013 no longer contains a RunPython backfill")


class _Recorder:
    """A historical registry that records what the migration asks it for.

    It delegates to the real registry so the queries still run; the point is
    only *which* registry the migration chose to ask.
    """

    def __init__(self):
        self.asked = []

    def get_model(self, app_label, model_name):
        self.asked.append((app_label, model_name))
        return live_apps.get_model(app_label, model_name)


# ── The structural fact, computed rather than asserted in prose ──────────────


def test_the_column_is_added_by_a_migration_that_runs_after_this_one():
    """0013 cannot see `audit_document_id`, and no reordering can change that.

    Read off the graph, not from memory: 0017 declares 0013 as a dependency, so
    the edge points one way and a reverse dependency would be a cycle.
    """
    loader = _loader()
    adder = loader.disk_migrations[ADDS_THE_COLUMN]

    added = {
        op.name
        for op in adder.operations
        if getattr(op, "model_name", "").lower() == "invoice"
        and hasattr(op, "field")
    }
    assert LATE_FIELD in added, (
        f"{ADDS_THE_COLUMN[1]} no longer adds {LATE_FIELD}; this guard is "
        "pointed at the wrong migration"
    )
    assert MIGRATION in adder.dependencies, (
        "the ordering that makes the column absent is gone — re-derive whether "
        "the historical registry is still the only safe one here"
    )


def test_the_historical_invoice_lacks_the_field_the_live_one_advertises():
    """The two registries disagree, and the disagreement is the whole defect."""
    before = _loader().project_state([MIGRATION], at_end=False)
    historical = before.apps.get_model("invoices", "Invoice")

    historical_fields = {f.name for f in historical._meta.get_fields()}
    live_fields = {f.name for f in live_apps.get_model("invoices", "Invoice")._meta.get_fields()}

    assert LATE_FIELD not in historical_fields, (
        "the database has no such column when 0013 runs"
    )
    assert LATE_FIELD in live_fields, (
        "the live model does have it — that mismatch is what produced 1054"
    )


@pytest.mark.django_db
def test_a_query_built_from_the_live_model_names_the_missing_column():
    """Reproduce the SQL that failed, without needing the old schema.

    This is the SELECT the shipped backfill sent: every concrete field of the
    model as defined today, including one the table does not have yet.
    """
    live_invoice = live_apps.get_model("invoices", "Invoice")
    sql = str(live_invoice.objects.filter(pk=uuid.uuid4()).query)
    assert f"{LATE_FIELD}_id" in sql, (
        "if the live model stopped selecting this column the 1054 would not "
        "have happened, and this guard is describing history, not behaviour"
    )


# ── The behaviour: which registry does the backfill actually ask? ────────────


@pytest.mark.django_db
def test_the_backfill_resolves_parents_through_the_registry_it_is_given():
    """The fix, driven end to end against a real row."""
    canonical = live_apps.get_model("documents", "DocumentCanonicalData")
    canonical.objects.create(
        document_type="invoice",
        typed_model_name="Invoice",
        typed_object_id=uuid.uuid4(),
    )

    recorder = _Recorder()
    _backfill()(recorder, None)

    assert ("documents", "DocumentCanonicalData") in recorder.asked
    parent_lookups = [a for a in recorder.asked if a[1] == "Invoice"]
    assert parent_lookups, (
        "the parent was resolved somewhere other than the registry the "
        "migration was handed — that registry is the live one, and its models "
        "describe columns this database does not have yet"
    )


@pytest.mark.django_db
def test_the_shipped_form_bypassed_that_registry(monkeypatch):
    """Plant the defect: the exact lookup 0013 shipped with, same harness.

    A guard that has not been seen failing is not a guard. This runs the two
    lines as they were written and shows the recorder never hears about the
    parent — which is why nothing caught it before the deploy did.
    """
    from django.apps import apps as django_apps  # the live registry, as shipped

    canonical = live_apps.get_model("documents", "DocumentCanonicalData")
    canonical.objects.create(
        document_type="invoice",
        typed_model_name="Invoice",
        typed_object_id=uuid.uuid4(),
    )

    recorder = _Recorder()
    Canonical = recorder.get_model("documents", "DocumentCanonicalData")
    for row in Canonical.objects.all().iterator(chunk_size=500):
        for app_label in ("documents", "invoices"):
            try:
                django_apps.get_model(app_label, row.typed_model_name)
                break
            except LookupError:
                continue

    assert not [a for a in recorder.asked if a[1] == "Invoice"], (
        "the planted defect no longer bypasses the historical registry, so "
        "this test can no longer prove the guard above discriminates"
    )


# ── The ratchet ──────────────────────────────────────────────────────────────


def test_no_migration_reaches_for_the_live_registry():
    """One offender existed when this was written. The count is computed.

    Deliberately not a list of filenames: a hand-written list in a header is
    what let this repository's first migration defect through.
    """
    loader = _loader()
    offenders = []
    for (app_label, name), migration in loader.disk_migrations.items():
        path = getattr(migration, "__module__", "")
        if not path:
            continue
        module = __import__(path, fromlist=["*"])
        source_file = getattr(module, "__file__", None)
        if not source_file:
            continue
        with open(source_file, encoding="utf-8") as handle:
            source = handle.read()
        if "from django.apps import apps" in source:
            offenders.append(f"{app_label}.{name}")

    assert offenders == [], (
        "a migration is importing the live app registry. Its models describe "
        "columns that may not exist yet at that point in the plan; use the "
        "`apps` argument RunPython is given. Offenders: " + ", ".join(offenders)
    )
