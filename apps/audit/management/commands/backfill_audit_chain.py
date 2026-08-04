"""
Backfill the hash chain for existing audit-event rows.

Existing rows ship with empty previous_hash/event_hash/chain_position. This
command walks every chain in chain_position-then-pk order, recomputes the
hashes, and persists them. Safe to re-run — once a row has a non-empty
event_hash, it is left alone.

Usage:
    python manage.py backfill_audit_chain
    python manage.py backfill_audit_chain --org-id <uuid>
    python manage.py backfill_audit_chain --dry-run
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.audit.integrity import GENESIS_HASH, HashChainMixin


class Command(BaseCommand):
    help = "Backfill previous_hash / event_hash / chain_position for existing audit rows."

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=str, default=None,
                            help="Restrict to a single organisation id.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Compute hashes but do not save.")

    def handle(self, *args, **opts):
        org_id = opts["org_id"]
        dry_run = opts["dry_run"]

        models = self._chain_models()
        if not models:
            self.stderr.write(self.style.WARNING("No HashChainMixin subclasses loaded."))
            return

        for Model in models:
            self.stdout.write(self.style.HTTP_INFO(f"\n▶ {Model.__module__}.{Model.__name__}"))
            self._backfill_model(Model, org_id, dry_run)

    # ── Internals ────────────────────────────────────────────────────────────

    def _chain_models(self) -> list[type]:
        out = []
        stack = list(HashChainMixin.__subclasses__())
        seen = set()
        while stack:
            cls = stack.pop()
            if cls in seen:
                continue
            seen.add(cls)
            if not getattr(cls._meta, "abstract", False):
                out.append(cls)
            stack.extend(cls.__subclasses__())
        return out

    def _backfill_model(self, Model, org_filter, dry_run):
        org_key = Model._chain_org_filter_key()
        qs = Model.objects.all()
        if org_filter:
            qs = qs.filter(**{org_key: org_filter})

        # Group rows by org so each org's chain stays self-contained.
        # Order: rows that already have a position keep it; new rows fall in
        # by their natural creation timestamp, with pk as the tiebreaker.
        # This matches the order the live save path would have assigned at
        # creation time.
        order_field = self._creation_order_field(Model)
        by_org: dict = defaultdict(list)
        for row in qs.order_by("chain_position", order_field, "pk"):
            org_id = self._get_org_id(row)
            by_org[org_id].append(row)

        total_rows  = sum(len(v) for v in by_org.values())
        skipped     = 0
        updated     = 0

        self.stdout.write(f"  rows: {total_rows}, orgs: {len(by_org)}")

        for org_id, rows in by_org.items():
            previous_hash = GENESIS_HASH
            position = 1
            for row in rows:
                if row.event_hash:
                    # Already chained — update running pointers and skip write.
                    previous_hash = row.event_hash
                    position = (row.chain_position or position) + 1
                    skipped += 1
                    continue

                # Freeze the partition and any model snapshot first — both are
                # inside the hash material, and the partition is what the
                # unique constraint and every later lookup filter on. Omitting
                # it leaves every tenant's rows in partition "", which collides
                # on the constraint and makes verification find nothing.
                row.chain_partition = str(org_id or "")
                row._freeze_chain_snapshot()
                row.previous_hash  = previous_hash
                row.chain_position = position
                event_hash = row.compute_hash(previous_hash)
                row.event_hash = event_hash
                row._after_chain_assigned()

                if not dry_run:
                    # Bypass the pre_save signal — it would refuse to set a
                    # hash on a row that already has a pk + zero-length hash.
                    # Written from _chain_written_fields() rather than a hand
                    # list so a new chain column cannot be forgotten here.
                    Model.objects.filter(pk=row.pk).update(**{
                        name: getattr(row, name)
                        for name in Model._chain_written_fields()
                    })

                previous_hash = event_hash
                position += 1
                updated += 1

            head_short = previous_hash[:16] + "…" if previous_hash != GENESIS_HASH else "(empty)"
            self.stdout.write(
                f"  org {org_id}: head={head_short}  "
                f"backfilled={updated - (updated - len(rows) + skipped)}/{len(rows)}"
            )

        verb = "would write" if dry_run else "wrote"
        self.stdout.write(self.style.SUCCESS(
            f"  {verb} {updated} row(s); {skipped} already chained."
        ))

    def _creation_order_field(self, Model) -> str:
        """Pick a field that approximates creation order for ``order_by``.

        Models in this codebase variously use ``created_at`` (most), ``timestamp``
        (InvoiceAuditEvent), or just an auto pk. We prefer the explicit time
        fields so backfill orders the same way the live save path did.
        """
        names = {f.name for f in Model._meta.get_fields()}
        for candidate in ("timestamp", "created_at", "added_at"):
            if candidate in names:
                return candidate
        return "pk"

    def _get_org_id(self, row):
        for attr in ("organization_id",):
            if hasattr(row, attr):
                v = getattr(row, attr)
                if v is not None:
                    return v
        # InvoiceAuditEvent → invoice → organization
        if hasattr(row, "invoice") and row.invoice:
            return row.invoice.organization_id
        return None
