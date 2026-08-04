"""
Tests for Phase 1.1 — Audit Trail Immutable Hash Chain.

Covers:
  • Linear chain: every new event links correctly to its predecessor.
  • Tamper detection: editing a row at the database layer breaks the chain
    and `verify_chain()` reports the exact position.
  • Cross-tenant isolation: events from different organisations live on
    independent chains.
  • Idempotent re-save: saving an already-chained row does not re-hash.
  • Signal block: trying to edit the payload of a chained row raises.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.audit.integrity import GENESIS_HASH, verify_chain
from apps.authentication.models import Organization, User
from apps.invoices.models import Invoice, InvoiceAuditEvent


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def org(db):
    return Organization.objects.create(name="Test Org Alpha")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Test Org Bravo")


@pytest.fixture
def user(db, org):
    return User.objects.create_user(
        email="alpha-auditor@test.local",
        full_name="Alpha Auditor",
        password="x",
        organization=org,
        role=User.Role.ADMIN,
    )


@pytest.fixture
def user_b(db, org_b):
    return User.objects.create_user(
        email="bravo-auditor@test.local",
        full_name="Bravo Auditor",
        password="x",
        organization=org_b,
        role=User.Role.ADMIN,
    )


@pytest.fixture
def invoice(db, org, user):
    return Invoice.objects.create(
        organization=org, uploaded_by=user,
        invoice_number="INV-CHAIN-1",
        vendor_name="ChainVendor",
        total_amount=100,
        original_filename="x.pdf",
    )


@pytest.fixture
def invoice_b(db, org_b, user_b):
    return Invoice.objects.create(
        organization=org_b, uploaded_by=user_b,
        invoice_number="INV-CHAIN-B",
        vendor_name="ChainVendorB",
        total_amount=200,
        original_filename="y.pdf",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Linear chain — every event links correctly
# ─────────────────────────────────────────────────────────────────────────────

def test_linear_chain_links_each_event(db, invoice, user):
    e1 = InvoiceAuditEvent.objects.create(
        invoice=invoice, user=user,
        event_type=InvoiceAuditEvent.EventType.UPLOADED,
        description="upload e1",
    )
    e2 = InvoiceAuditEvent.objects.create(
        invoice=invoice, user=user,
        event_type=InvoiceAuditEvent.EventType.PROCESSED,
        description="process e2",
    )
    e3 = InvoiceAuditEvent.objects.create(
        invoice=invoice, user=user,
        event_type=InvoiceAuditEvent.EventType.VALIDATED,
        description="validate e3",
    )

    e1.refresh_from_db(); e2.refresh_from_db(); e3.refresh_from_db()

    assert e1.previous_hash == GENESIS_HASH
    assert e1.event_hash != ""
    assert e1.chain_position == 1

    assert e2.previous_hash == e1.event_hash
    assert e2.event_hash != e1.event_hash
    assert e2.chain_position == 2

    assert e3.previous_hash == e2.event_hash
    assert e3.chain_position == 3

    rep = verify_chain(InvoiceAuditEvent, str(invoice.organization_id))
    assert rep.is_intact
    assert rep.rows_checked == 3
    assert rep.head_hash == e3.event_hash


# ─────────────────────────────────────────────────────────────────────────────
# 2. Tamper detection
# ─────────────────────────────────────────────────────────────────────────────

def test_tampering_via_raw_update_is_detected(db, invoice, user):
    e1 = InvoiceAuditEvent.objects.create(
        invoice=invoice, user=user,
        event_type=InvoiceAuditEvent.EventType.UPLOADED,
        description="upload",
    )
    e2 = InvoiceAuditEvent.objects.create(
        invoice=invoice, user=user,
        event_type=InvoiceAuditEvent.EventType.APPROVED,
        description="approved",
    )

    rep = verify_chain(InvoiceAuditEvent, str(invoice.organization_id))
    assert rep.is_intact, "Pre-tamper chain should be clean"

    # Tamper directly via .update() — bypasses the pre_save signal so this
    # mimics a SQL-shell edit / restored-from-backup row swap.
    InvoiceAuditEvent.objects.filter(pk=e1.pk).update(description="TAMPERED")

    rep = verify_chain(InvoiceAuditEvent, str(invoice.organization_id))
    assert not rep.is_intact, "Chain must report tampered row"
    assert rep.break_count if hasattr(rep, "break_count") else len(rep.breaks) >= 1
    # The first break must be at e1's position.
    first = rep.breaks[0]
    assert first.chain_position == e1.chain_position
    assert first.reason in {"event_hash_mismatch", "previous_hash_mismatch"}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Cross-tenant isolation
# ─────────────────────────────────────────────────────────────────────────────

def test_chains_are_per_organization(db, invoice, invoice_b, user, user_b):
    a1 = InvoiceAuditEvent.objects.create(
        invoice=invoice, user=user,
        event_type=InvoiceAuditEvent.EventType.UPLOADED, description="A1",
    )
    b1 = InvoiceAuditEvent.objects.create(
        invoice=invoice_b, user=user_b,
        event_type=InvoiceAuditEvent.EventType.UPLOADED, description="B1",
    )
    a2 = InvoiceAuditEvent.objects.create(
        invoice=invoice, user=user,
        event_type=InvoiceAuditEvent.EventType.PROCESSED, description="A2",
    )

    a1.refresh_from_db(); a2.refresh_from_db(); b1.refresh_from_db()

    # Each org's chain starts at GENESIS independently.
    assert a1.previous_hash == GENESIS_HASH
    assert b1.previous_hash == GENESIS_HASH

    # A's chain links A1 → A2, ignoring B1 entirely.
    assert a2.previous_hash == a1.event_hash
    assert a2.previous_hash != b1.event_hash

    # Each chain verifies independently.
    rep_a = verify_chain(InvoiceAuditEvent, str(invoice.organization_id))
    rep_b = verify_chain(InvoiceAuditEvent, str(invoice_b.organization_id))
    assert rep_a.is_intact and rep_a.rows_checked == 2
    assert rep_b.is_intact and rep_b.rows_checked == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. Idempotent re-save
# ─────────────────────────────────────────────────────────────────────────────

def test_resaving_chained_row_does_not_rehash(db, invoice, user):
    e = InvoiceAuditEvent.objects.create(
        invoice=invoice, user=user,
        event_type=InvoiceAuditEvent.EventType.UPLOADED,
        description="immutable",
    )
    original_hash = e.event_hash
    original_pos = e.chain_position

    # No-op save (no payload changes) — must NOT re-hash.
    e.save()

    e.refresh_from_db()
    assert e.event_hash == original_hash
    assert e.chain_position == original_pos


# ─────────────────────────────────────────────────────────────────────────────
# 5. Signal blocks payload mutations
# ─────────────────────────────────────────────────────────────────────────────

def test_editing_payload_field_is_rejected(db, invoice, user):
    e = InvoiceAuditEvent.objects.create(
        invoice=invoice, user=user,
        event_type=InvoiceAuditEvent.EventType.UPLOADED,
        description="original",
    )
    e.description = "tampered"
    with pytest.raises(ValidationError):
        e.save()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Backfill is deterministic
# ─────────────────────────────────────────────────────────────────────────────

def test_backfill_is_deterministic(db, invoice, user):
    """Wiping the chain and re-running backfill must produce the same head."""
    from django.core.management import call_command

    InvoiceAuditEvent.objects.create(
        invoice=invoice, user=user,
        event_type=InvoiceAuditEvent.EventType.UPLOADED, description="A",
    )
    InvoiceAuditEvent.objects.create(
        invoice=invoice, user=user,
        event_type=InvoiceAuditEvent.EventType.PROCESSED, description="B",
    )

    rep1 = verify_chain(InvoiceAuditEvent, str(invoice.organization_id))
    head1 = rep1.head_hash

    # Wipe + rebuild.
    # chain_position=None, not 0. An unchained row now has no position at all:
    # 0 was a value, so N unchained rows in a partition were N copies of
    # (partition, 0) and collided on the unique constraint that makes a fork
    # impossible. NULL is the one "unset" a unique index ignores.
    InvoiceAuditEvent.objects.all().update(
        previous_hash="", event_hash="", chain_position=None, chain_partition="",
    )
    call_command("backfill_audit_chain", verbosity=0)

    rep2 = verify_chain(InvoiceAuditEvent, str(invoice.organization_id))
    assert rep2.is_intact
    assert rep2.head_hash == head1, (
        "Backfill must reproduce the same head hash given the same input rows."
    )
