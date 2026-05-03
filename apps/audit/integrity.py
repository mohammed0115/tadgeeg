"""
Audit-trail integrity — Phase 1.1 of the Enterprise Roadmap.

Every model that records an audit-relevant event inherits from
`HashChainMixin`. Each row carries:

  • previous_hash  — the hash of the row immediately before this one in the
                     same organisation's chain.
  • event_hash     — SHA-256 of (previous_hash + canonical_payload + iso_ts
                     + organization_id). Computed automatically on first save.
  • chain_position — monotonically increasing position within the org chain.

The chain is *append-only* by convention: `pre_save` and `pre_delete` signals
block any post-creation mutation. Tampering with a row in the database (via
SQL shell) is not prevented, but it *is* detectable — `verify_chain()` walks
the chain and reports the first row whose stored `event_hash` no longer
matches the recomputed value, or whose `previous_hash` does not match the
prior row's `event_hash`.

This is exactly the "tamper-evident" property that ISA 700 / SOX auditors
expect from working-paper trails. It is not a blockchain — there is no
distributed consensus — but it gives the auditor a single tripwire that
fires the moment the application's history is mutated.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from django.db import models, transaction
from django.utils import timezone

logger = logging.getLogger("finai")

# ─────────────────────────────────────────────────────────────────────────────
# Mixin
# ─────────────────────────────────────────────────────────────────────────────

GENESIS_HASH = "0" * 64
"""The "previous_hash" value used at the head of every chain — corresponds to
SHA-256(""), but a string of zeros is easier to spot in logs/exports."""


class HashChainMixin(models.Model):
    """Abstract base that adds tamper-evident chaining to any model.

    Subclasses must implement ``_chain_payload()`` returning a JSON-serialisable
    dict that captures the immutable fields of the row (everything that, if
    edited, should break the chain).

    Subclasses must also implement ``_chain_organization_id()`` so each org
    keeps its own independent chain — otherwise re-ordering events across
    tenants would silently re-link them.
    """

    previous_hash  = models.CharField(max_length=64, blank=True, default="",
                                      help_text="event_hash of the previous row in this org's chain")
    event_hash     = models.CharField(max_length=64, blank=True, default="", db_index=True,
                                      help_text="SHA-256(previous_hash + payload + ts + org)")
    chain_position = models.PositiveBigIntegerField(default=0, db_index=True,
                                                    help_text="1-based position within this org's chain")

    class Meta:
        abstract = True

    # ── To be implemented by subclasses ──────────────────────────────────────

    def _chain_payload(self) -> dict:
        """Return the canonical, JSON-serialisable payload that the row's hash
        commits to. Override in subclasses."""
        raise NotImplementedError

    def _chain_organization_id(self) -> Optional[Any]:
        """Return the organization id this row belongs to. Each org has its
        own chain, so this is the partitioning key."""
        raise NotImplementedError

    def _should_chain_now(self) -> bool:
        """Override to defer chain assignment until a domain-specific event.

        Default: chain on first save (used by InvoiceAuditEvent — every event
        is locked the moment it's recorded).

        Working papers override this to ``False`` while in draft, then return
        ``True`` once the partner signs and the paper transitions to LOCKED —
        the chain protects only the *finalised* working paper, while the
        preparer is free to edit it during the review cycle.
        """
        return True

    def lock_chain(self) -> None:
        """Force chain assignment now. Use when a model defers chaining via
        ``_should_chain_now``. Idempotent — once chained, this is a no-op.
        Persisting the new fields is the caller's responsibility."""
        if not self.event_hash:
            assign_chain_fields(self)

    # ── Hash math ────────────────────────────────────────────────────────────

    def compute_hash(self, previous_hash: str, timestamp_iso: str = "") -> str:
        """SHA-256 of (previous_hash + canonical_payload + organization_id).

        The serialisation uses ``sort_keys=True`` and ``separators=(",", ":")``
        so the same Python dict always produces the same bytes — without that
        guarantee the chain breaks on every Python interpreter restart.

        Note: the timestamp is *inside* the payload (under ``__chain_ts__`` for
        models with auto-populated timestamps). It is not added separately to
        the hash material — that would double-count the field, and worse,
        any drift between "save-time wallclock" and "auto_now_add field value"
        would cause the chain to break on backfill. Keeping the timestamp in
        the payload only is what makes hashing deterministic.
        """
        org_id = str(self._chain_organization_id() or "")
        payload = json.dumps(self._chain_payload(), sort_keys=True, separators=(",", ":"),
                             default=_json_default)
        material = f"{previous_hash}|{payload}|{org_id}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()


def _json_default(obj):
    """JSON serializer fallback for UUIDs, dates, decimals, etc."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


# ─────────────────────────────────────────────────────────────────────────────
# Hash assignment on save
# ─────────────────────────────────────────────────────────────────────────────

def assign_chain_fields(instance) -> None:
    """Compute and assign previous_hash / event_hash / chain_position.

    Idempotent: once a row has a non-empty event_hash it is never re-hashed.
    This is critical — re-hashing on every save would defeat the chain.
    """
    if instance.event_hash:
        return  # already chained

    org_id = instance._chain_organization_id()
    Model = instance.__class__

    # Lock the most-recent row in this org's chain so two concurrent creates
    # cannot end up with the same chain_position.
    with transaction.atomic():
        previous = (
            Model.objects.select_for_update(skip_locked=False)
            .filter(**{Model._chain_org_filter_key(): org_id})
            .exclude(pk=instance.pk)
            .order_by("-chain_position")
            .first()
        )

        if previous and previous.event_hash:
            instance.previous_hash  = previous.event_hash
            instance.chain_position = (previous.chain_position or 0) + 1
        else:
            instance.previous_hash  = GENESIS_HASH
            instance.chain_position = 1

        # The timestamp goes inside the payload (`__chain_ts__`) — see
        # compute_hash docstring for why we don't pass it separately.
        instance.event_hash = instance.compute_hash(instance.previous_hash)


# ─────────────────────────────────────────────────────────────────────────────
# Chain verification
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ChainBreak:
    chain_position: int
    row_id: str
    reason: str
    expected: str = ""
    actual: str = ""

    def to_dict(self) -> dict:
        return {
            "chain_position": self.chain_position,
            "row_id": self.row_id,
            "reason": self.reason,
            "expected": self.expected[:16] + "…" if self.expected else "",
            "actual":   self.actual[:16]   + "…" if self.actual   else "",
        }


@dataclass
class ChainReport:
    model: str
    organization_id: str
    rows_checked: int = 0
    head_hash: str = ""
    is_intact: bool = True
    breaks: list[ChainBreak] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "organization_id": str(self.organization_id),
            "rows_checked": self.rows_checked,
            "head_hash": self.head_hash[:16] + "…" if self.head_hash else "",
            "head_hash_full": self.head_hash,
            "is_intact": self.is_intact,
            "break_count": len(self.breaks),
            "breaks": [b.to_dict() for b in self.breaks],
        }


def verify_chain(model_cls, organization_id) -> ChainReport:
    """Walk a chain in increasing chain_position order and report any break.

    Returns a ChainReport with `is_intact=True` for an unblemished chain, or
    a list of breaks pinning the exact row that diverged.
    """
    rows = (
        model_cls.objects
        .filter(**{model_cls._chain_org_filter_key(): organization_id})
        .order_by("chain_position", "pk")
    )
    report = ChainReport(model=model_cls.__name__, organization_id=organization_id)
    expected_previous = GENESIS_HASH

    for row in rows.iterator(chunk_size=500):
        report.rows_checked += 1

        if not row.event_hash:
            report.is_intact = False
            report.breaks.append(ChainBreak(
                chain_position=row.chain_position,
                row_id=str(row.pk),
                reason="missing_event_hash",
            ))
            continue

        if row.previous_hash != expected_previous:
            report.is_intact = False
            report.breaks.append(ChainBreak(
                chain_position=row.chain_position,
                row_id=str(row.pk),
                reason="previous_hash_mismatch",
                expected=expected_previous,
                actual=row.previous_hash,
            ))

        # Recompute and compare. Use the *stored* previous_hash for the
        # recomputation so a single tampered row only fails its own line —
        # otherwise every subsequent row would also fail.
        recomputed = row.compute_hash(row.previous_hash)
        if recomputed != row.event_hash:
            report.is_intact = False
            report.breaks.append(ChainBreak(
                chain_position=row.chain_position,
                row_id=str(row.pk),
                reason="event_hash_mismatch",
                expected=row.event_hash,
                actual=recomputed,
            ))

        expected_previous = row.event_hash

    report.head_hash = expected_previous if expected_previous != GENESIS_HASH else ""
    return report
