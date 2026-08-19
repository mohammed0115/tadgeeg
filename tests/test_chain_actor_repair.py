"""A migration wrote chain_actor in the column's spelling, and verification broke.

`verify_chain()` reported tampering on rows nobody had touched. Two migrations
in one batch disagreed about how a UUID is written:

    authentication/0010  hashed str(row.user_id)      -> "085f9a13-0915-..."
    authentication/0011  chain_actor=models.F("user_id") -> "085f9a13091546..."

`F()` copies the column, and MySQL stores a UUIDField as char(32) without
hyphens. `_chain_payload()` reads chain_actor, so the verifier hashes a
different string from the one the stored hash commits to.

tests/test_audit_trail_integrity.py already asserted that an untouched chain
verifies — and passed throughout, because it builds its rows through the Python
path where both spellings agree. It never went near the backfill. That is what
these tests add: the migration's path, planted.
"""

import uuid

import pytest
from django.core.management import call_command
from io import StringIO

from apps.audit.integrity import verify_chain
from apps.authentication.models import AuditLog, Organization, User


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Chain Actor Org")


@pytest.fixture
def user(db, org):
    return User.objects.create_user(
        email="chain-actor@test.local", full_name="Chain Actor", password="x",
        organization=org, role=User.Role.ADMIN,
    )


@pytest.fixture
def entry(db, org, user):
    row = AuditLog.objects.create(
        organization=org, user=user, action="user_updated",
        resource_type="User", resource_id=str(user.pk), details={"k": "v"},
    )
    row.refresh_from_db()
    return row


def _as_the_migration_wrote_it(row):
    """chain_actor as `F("user_id")` produces it: the column, no hyphens.

    `.update()` and not `.save()` — the pre_save signal owns the chain fields
    and would refuse. It is also what the migration did.
    """
    AuditLog.objects.filter(pk=row.pk).update(chain_actor=uuid.UUID(str(row.user_id)).hex)
    row.refresh_from_db()
    return row


def test_the_python_path_agrees_with_itself(entry, org):
    """Baseline, and the reason the existing guard never saw this."""
    assert "-" in entry.chain_actor
    assert verify_chain(AuditLog, str(org.pk)).is_intact


def test_the_migrations_spelling_breaks_verification(entry, org):
    """The planted defect: an untouched row that reads as tampered with."""
    _as_the_migration_wrote_it(entry)

    assert "-" not in entry.chain_actor
    report = verify_chain(AuditLog, str(org.pk))
    assert not report.is_intact
    assert any(b.reason == "event_hash_mismatch" for b in report.breaks)


def test_the_repair_restores_verification(entry, org):
    _as_the_migration_wrote_it(entry)
    assert not verify_chain(AuditLog, str(org.pk)).is_intact

    call_command("repair_chain_actor", "--apply", stdout=StringIO())

    assert verify_chain(AuditLog, str(org.pk)).is_intact


def test_the_repair_writes_no_hash(entry, org):
    """The record is intact; only the derived field was wrong.

    If a repair rewrote event_hash it would be manufacturing the verification
    it reports, which is the failure this whole file exists to catch.
    """
    before = _as_the_migration_wrote_it(entry)
    hashes = (before.event_hash, before.previous_hash, before.chain_position)

    call_command("repair_chain_actor", "--apply", stdout=StringIO())
    before.refresh_from_db()

    assert (before.event_hash, before.previous_hash, before.chain_position) == hashes


def test_without_apply_nothing_is_written(entry, org):
    _as_the_migration_wrote_it(entry)
    actor = entry.chain_actor

    call_command("repair_chain_actor", stdout=StringIO())
    entry.refresh_from_db()

    assert entry.chain_actor == actor
    assert not verify_chain(AuditLog, str(org.pk)).is_intact


def test_a_row_that_stays_broken_is_reported_not_rewritten(entry, org):
    """Not every mismatch is this defect, and the rest must not be papered over."""
    AuditLog.objects.filter(pk=entry.pk).update(details={"tampered": True})

    out = StringIO()
    call_command("repair_chain_actor", "--apply", stdout=out)
    entry.refresh_from_db()

    assert "غير مفسَّر: 1" in out.getvalue()
    assert not verify_chain(AuditLog, str(org.pk)).is_intact, (
        "an edited row was made to verify again — the chain would prove nothing"
    )


def test_apply_prints_the_reversal_before_writing(entry, org):
    """A backup that predates eight migrations is not a reversal plan.

    Each write is one column on one row, so the undo is one UPDATE — and it is
    only an undo if the former value was recorded before it was overwritten.
    """
    _as_the_migration_wrote_it(entry)
    entry.refresh_from_db()
    former = entry.chain_actor

    out = StringIO()
    call_command("repair_chain_actor", "--apply", stdout=out)
    printed = out.getvalue()

    assert f"SET chain_actor='{former}'" in printed
    assert str(entry.pk) in printed
    entry.refresh_from_db()
    assert entry.chain_actor != former, "the reversal was printed but nothing was written"
