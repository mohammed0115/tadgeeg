"""Rebuild AuditLog's chain per organisation, with positions.

Rows written before this change carry a `chain_hash` from the old
implementation, which chained **globally** — one organisation's entry hashed
off another's — and had no `chain_position` at all. Those rows cannot simply be
left alone: `verify_chain()` walks by `chain_position`, so every pre-existing
row would come back position 0 and the chain would read as broken from the
first record.

Nor can the old hashes be kept. They commit to a predecessor that, under the
new per-tenant partition, is no longer the predecessor. Keeping them would
leave a chain that fails verification forever — an audit log permanently
reporting tampering that never happened is worse than one that reports nothing,
because the first thing anyone does with a boy-who-cried-wolf alarm is stop
reading it.

So the chains are rebuilt: rows are ordered per organisation by timestamp then
pk, given sequential positions, and re-hashed with the new payload. What this
does and does not prove is worth stating plainly:

  · it does NOT retroactively prove the old rows were untampered. Nothing can;
    the old chain was global and forkable, so it never proved that either.
  · it DOES establish a verifiable baseline from this migration forward. Every
    row written after it is covered by the locked, positioned, per-tenant
    chain.

`chain_hash` is preserved as a mirror of the new `event_hash` so existing
readers and exports keep working.
"""

from django.db import migrations


def rebuild_chains(apps, schema_editor):
    import hashlib
    import json

    from apps.audit.integrity import GENESIS_HASH

    AuditLog = apps.get_model("authentication", "AuditLog")

    # Historical model — no HashChainMixin methods available here, so the hash
    # is computed inline. It must match apps/audit/integrity.py::compute_hash;
    # test_audit_trail_integrity.py asserts a migrated row still verifies,
    # which is what keeps the two in step.
    def _json_default(obj):
        # Mirrors apps/audit/integrity.py::_json_default exactly. A different
        # fallback here produces different bytes for the same row, and the
        # rebuilt chain would fail the very verification it exists to enable.
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)

    organisation_ids = list(
        AuditLog.objects.values_list("organization_id", flat=True).distinct()
    )

    for organization_id in organisation_ids:
        rows = list(
            AuditLog.objects
            .filter(organization_id=organization_id)
            # timestamp then pk: timestamps tie, and a tie needs a stable
            # tiebreak or the rebuild is not reproducible.
            .order_by("timestamp", "pk")
        )

        previous_hash = GENESIS_HASH
        for position, row in enumerate(rows, start=1):
            payload = {
                "action": row.action,
                "user_id": str(row.user_id) if row.user_id else None,
                "organization_id": str(row.organization_id) if row.organization_id else None,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "details": row.details,
            }
            # Byte-for-byte the same material as
            # HashChainMixin.compute_hash: f"{previous_hash}|{payload}|{org_id}"
            # with sort_keys=True and separators=(",", ":"). Any deviation and
            # every rebuilt row fails verification.
            serialised = json.dumps(payload, sort_keys=True,
                                    separators=(",", ":"), default=_json_default)
            org_id = str(organization_id or "")
            material = f"{previous_hash}|{serialised}|{org_id}".encode("utf-8")
            event_hash = hashlib.sha256(material).hexdigest()

            AuditLog.objects.filter(pk=row.pk).update(
                previous_hash=previous_hash,
                event_hash=event_hash,
                chain_hash=event_hash,
                chain_position=position,
            )
            previous_hash = event_hash


def unrebuild(apps, schema_editor):
    """Reverse: clear the new columns.

    The old global chain is not restored — it was not reconstructible from the
    rows alone, and restoring a forkable chain would be an odd thing to want.
    Reversing this migration leaves the trail unchained, which is honest about
    what reversing it means.
    """
    AuditLog = apps.get_model("authentication", "AuditLog")
    AuditLog.objects.update(event_hash="", chain_position=0)


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0009_unify_hash_chain"),
    ]

    operations = [
        migrations.RunPython(rebuild_chains, unrebuild),
    ]
