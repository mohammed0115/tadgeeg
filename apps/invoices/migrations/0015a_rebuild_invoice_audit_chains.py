"""Rebuild InvoiceAuditEvent's chain per organisation, with positions.

`0016` adds `uniq_chain_position_invoiceauditevent` and assumes the rows it
meets already form one chain per partition. On a real database they do not.
Measured on a copy of production data, 2026-08-18:

    IntegrityError: (1062, "Duplicate entry
      '88bc8c33-fbb0-48cb-963b-62220dc5b2bb-13'
      for key 'invoice_audit_events.uniq_chain_position_invoiceauditevent'")

Nine positions in one organisation's chain hold more than one row, and twelve
rows hold no position at all. Every collision has the same shape: two events
carrying the *same* `previous_hash` and different `event_hash` — they read the
same chain head, computed the same next position, and both wrote. `uploaded` is
always the later of the pair, because it is written when the long upload
transaction commits while `processed` was written inside it.

    13  processed  20:27:35  prev=0cb1e7e04a  hash=8eea413c3e
    13  uploaded   20:27:44  prev=0cb1e7e04a  hash=cb288bf24b

`activity_logs` and `authentication` were given `unify` + `rebuild` before
their fork constraint. `invoices` was given the constraint alone. This is the
missing step, and it is deliberately the same step: rows are ordered per
organisation by timestamp then pk, given sequential positions, and re-hashed
with the material `compute_hash` produces. What that does and does not prove is
worth stating plainly, and it is the same statement authentication/0010 makes:

  · it does NOT retroactively prove the old rows were untampered. Nothing can;
    a chain that could fork never proved that either.
  · it DOES establish a verifiable baseline from this migration forward, and
    it lets 0016's constraint build — after which a concurrent write fails
    loudly instead of forking the chain in silence.

No row is deleted. Positions and hashes change; `event_type`, `timestamp`,
`before_data`, `after_data` and every other recorded fact do not.

The residual risk is recorded rather than fixed here: two concurrent writers
still race, and after 0016 the loser gets an IntegrityError instead of a fork.
`apps/audit/integrity.py` retries such a conflict CHAIN_INSERT_RETRIES times,
so the visible outcome should be a slower write, not a failed one — but that
path has not been measured under the upload transaction's lock duration.
"""

from django.db import migrations

# Inlined, not imported from apps.audit.integrity — a historical migration must
# not depend on live application code. Renaming that module or moving this
# value into settings would break `migrate` on every fresh database while
# already-migrated ones carried on silently. compute_hash is hand-copied below
# for the same reason; tests/test_invoice_chain_rebuild.py asserts both still
# match their originals.
GENESIS_HASH = "0" * 64

#: Rows re-hashed per bulk_update round-trip.
BATCH = 1000


def rebuild_chains(apps, schema_editor):
    import hashlib
    import json

    InvoiceAuditEvent = apps.get_model("invoices", "InvoiceAuditEvent")

    def _json_default(obj):
        # Mirrors apps/audit/integrity.py::_json_default exactly. A different
        # fallback produces different bytes for the same row, and the rebuilt
        # chain would fail the verification it exists to enable.
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)

    # .order_by() with no arguments is load-bearing, not tidiness.
    #
    # InvoiceAuditEvent.Meta.ordering is ["-timestamp"], and it survives onto
    # the historical model. Django appends ordering columns to the SELECT list
    # of a DISTINCT query, so without this the query would be distinct over
    # (organization_id, timestamp) — one row per event, not per organisation —
    # and the loop below would rebuild each organisation once per event.
    organisation_ids = list(
        InvoiceAuditEvent.objects
        .order_by()
        .values_list("invoice__organization_id", flat=True)
        .distinct()
    )

    rebuilt = 0
    for organization_id in organisation_ids:
        rows = (
            InvoiceAuditEvent.objects
            .filter(invoice__organization_id=organization_id)
            # timestamp then pk: timestamps tie — the collisions this migration
            # exists for are seconds apart — and a tie needs a stable tiebreak
            # or the rebuild is not reproducible.
            .order_by("timestamp", "pk")
            .iterator(chunk_size=BATCH)
        )

        previous_hash = GENESIS_HASH
        position = 0
        batch = []

        for row in rows:
            position += 1
            # Mirrors InvoiceAuditEvent._chain_payload(). `timestamp` is absent
            # from it on purpose — auto_now_add populates the field after the
            # chain signal runs, so hashing it would make the chain
            # non-deterministic. pk and chain_position already encode order.
            payload = {
                "id":          str(row.id),
                "invoice_id":  str(row.invoice_id),
                "user_id":     str(row.user_id) if row.user_id else None,
                "event_type":  row.event_type,
                "description": row.description or "",
                "before_data": row.before_data or {},
                "after_data":  row.after_data or {},
                "ip_address":  row.ip_address or "",
            }
            serialised = json.dumps(payload, sort_keys=True,
                                    separators=(",", ":"), default=_json_default)
            # The partition string, byte-for-byte what compute_hash builds:
            # assign_chain_fields writes str(_chain_organization_id() or "")
            # into chain_partition, and 0016's freeze_partitions writes the same
            # value. This migration runs before that column exists, so it is
            # derived from the organisation directly — the same string.
            partition = str(organization_id or "")
            material = f"{previous_hash}|{serialised}|{partition}".encode("utf-8")
            event_hash = hashlib.sha256(material).hexdigest()

            row.previous_hash = previous_hash
            row.event_hash = event_hash
            row.chain_position = position
            batch.append(row)

            if len(batch) >= BATCH:
                InvoiceAuditEvent.objects.bulk_update(
                    batch, ["previous_hash", "event_hash", "chain_position"]
                )
                batch = []

            previous_hash = event_hash

        if batch:
            InvoiceAuditEvent.objects.bulk_update(
                batch, ["previous_hash", "event_hash", "chain_position"]
            )
        rebuilt += position

    print(
        f"\n[invoices rebuild] organisations={len(organisation_ids)} "
        f"events_repositioned={rebuilt}"
    )


def unrebuild(apps, schema_editor):
    """Reverse: clear every field this migration wrote.

    The pre-rebuild positions are not restored. They were not reconstructible
    from the rows alone — that is the whole reason this migration exists — and
    restoring a set of positions with known collisions would only put back the
    state that stops 0016 applying. Reversing leaves the trail unchained, which
    is honest about what reversing means.

    `chain_position=0`, not None. Django reverses in reverse dependency order,
    so 0016 — the migration that makes this column nullable — has already been
    undone by the time this runs, and writing None into it would fail.
    """
    InvoiceAuditEvent = apps.get_model("invoices", "InvoiceAuditEvent")
    InvoiceAuditEvent.objects.update(
        previous_hash="", event_hash="", chain_position=0,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0015_invoice_control_risk_invoice_detection_risk_and_more"),
    ]

    operations = [
        migrations.RunPython(rebuild_chains, unrebuild),
    ]
