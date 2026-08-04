"""Rebuild ActivityLog's chain per organisation, with positions.

The counterpart to authentication/0010, and missing from the commit that made
it necessary. 0004 gave ActivityLog the new schema — `event_hash` defaulting to
"" and `chain_position` defaulting to 0 — and stopped there. Every row written
before that point would therefore have reported `missing_event_hash` on the
integrity page forever, which is exactly the outcome authentication/0010's
docstring argues against, applied to the other model in the same change.

That mattered more than it looks: apps/frontend/page_views.py auto-discovers
every concrete HashChainMixin subclass, so ActivityLog appears on the
customer-facing integrity page the moment it inherits the mixin. Un-backfilled
rows would have been shown to auditors as a broken chain.

The same caveat as 0010 applies and is worth repeating rather than assuming:
this does not retroactively prove the old rows were untampered — the old chain
had no lock and no position, so it never proved that either. It establishes a
verifiable baseline from here forward. The pre-existing `chain_hash` values are
kept until each row is re-chained, so nothing is destroyed on the way.
"""

from django.db import migrations

# Inlined deliberately — see the same constant in authentication/0010 for why a
# historical migration must not import live application code.
GENESIS_HASH = "0" * 64

#: Rows re-hashed per bulk_update round-trip.
BATCH = 1000


def rebuild_chains(apps, schema_editor):
    import hashlib
    import json

    ActivityLog = apps.get_model("activity_logs", "ActivityLog")

    def _json_default(obj):
        # Mirrors apps/audit/integrity.py::_json_default exactly.
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)

    # .order_by() clears Meta.ordering (["-created_at"]) before .distinct().
    # Without it Django appends created_at to the DISTINCT select list and the
    # result is distinct over (organization_id, created_at) — one entry per
    # row rather than per organisation. See authentication/0010 for the full
    # account; it cost that migration a quadratic loop.
    organisation_ids = list(
        ActivityLog.objects
        .order_by()
        .values_list("organization_id", flat=True)
        .distinct()
    )

    for organization_id in organisation_ids:
        rows = (
            ActivityLog.objects
            .filter(organization_id=organization_id)
            # created_at then pk: timestamps tie, and a tie needs a stable
            # tiebreak or the rebuild is not reproducible.
            .order_by("created_at", "pk")
            .iterator(chunk_size=BATCH)
        )

        previous_hash = GENESIS_HASH
        position = 0
        batch = []

        for row in rows:
            position += 1
            # Must match ActivityLog._chain_payload() exactly — same keys, same
            # order-independent serialisation — or every rebuilt row fails the
            # verification this migration exists to enable.
            payload = {
                "org":         str(row.organization_id or ""),
                "user":        str(row.user_id or ""),
                "action":      row.action,
                "entity_type": row.entity_type,
                "entity_id":   row.entity_id,
                "ip":          str(row.ip_address or ""),
                "metadata":    row.metadata or {},
            }
            serialised = json.dumps(payload, sort_keys=True,
                                    separators=(",", ":"), default=_json_default)
            org_id = str(organization_id or "")
            material = f"{previous_hash}|{serialised}|{org_id}".encode("utf-8")
            event_hash = hashlib.sha256(material).hexdigest()

            row.previous_hash = previous_hash
            row.event_hash = event_hash
            row.chain_hash = event_hash
            row.chain_position = position
            batch.append(row)

            if len(batch) >= BATCH:
                ActivityLog.objects.bulk_update(
                    batch,
                    ["previous_hash", "event_hash", "chain_hash", "chain_position"],
                )
                batch = []

            previous_hash = event_hash

        if batch:
            ActivityLog.objects.bulk_update(
                batch,
                ["previous_hash", "event_hash", "chain_hash", "chain_position"],
            )


def unrebuild(apps, schema_editor):
    """Reverse: clear every field this migration wrote.

    Including `previous_hash` and `chain_hash`, which the forward pass
    overwrote in the new per-org format. Leaving them would hand rolled-back
    code hashes computed under a formula it does not use, and it would read
    them as tampering.
    """
    ActivityLog = apps.get_model("activity_logs", "ActivityLog")
    ActivityLog.objects.update(
        previous_hash="", event_hash="", chain_hash="", chain_position=0,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("activity_logs", "0004_unify_hash_chain"),
    ]

    operations = [
        migrations.RunPython(rebuild_chains, unrebuild),
    ]
