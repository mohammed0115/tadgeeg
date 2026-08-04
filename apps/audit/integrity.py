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

from django.db import IntegrityError, models, transaction
from django.utils import timezone

logger = logging.getLogger("finai")

# ─────────────────────────────────────────────────────────────────────────────
# Mixin
# ─────────────────────────────────────────────────────────────────────────────

GENESIS_HASH = "0" * 64
"""The "previous_hash" value used at the head of every chain — corresponds to
SHA-256(""), but a string of zeros is easier to spot in logs/exports."""

#: How many times an insert may lose the race for a chain position before it
#: gives up. Contention is resolved by the database's unique constraint, so a
#: retry is cheap and a loop this short is only ever exercised under genuine
#: concurrency. Five is far above what real traffic produces; it exists so a
#: pathological burst fails loudly instead of spinning.
CHAIN_INSERT_RETRIES = 5


def _is_position_conflict(exc, constraint_name: str) -> bool:
    """Is this IntegrityError "someone took my chain position", or something else?

    Only the former may be retried; retrying a genuine integrity failure would
    hide it behind CHAIN_INSERT_RETRIES attempts and then a misleading error.

    Backends disagree on what they put in the message, and the difference is
    not cosmetic — matching only the constraint name meant the retry worked on
    MySQL and never fired on SQLite, so every test in this project's suite
    would have reported the mechanism as broken while production was fine:

      MySQL   Duplicate entry 'x-1' for key 'uniq_chain_position_auditlog'
      SQLite  UNIQUE constraint failed: audit_logs.chain_partition,
              audit_logs.chain_position

    So both shapes are recognised.
    """
    message = str(exc).lower()
    if constraint_name.lower() in message:
        return True
    return "chain_partition" in message and "chain_position" in message


class ChainContentionError(Exception):
    """Raised when an append lost the position race CHAIN_INSERT_RETRIES times.

    Loud on purpose. The alternative — writing the row unchained — would leave
    a gap in a trail whose only value is that it has no gaps.
    """


class HashChainMixin(models.Model):
    """Abstract base that adds tamper-evident chaining to any model.

    Subclasses must implement ``_chain_payload()`` returning a JSON-serialisable
    dict that captures the immutable fields of the row (everything that, if
    edited, should break the chain).

    Subclasses must also implement ``_chain_organization_id()`` so each org
    keeps its own independent chain — otherwise re-ordering events across
    tenants would silently re-link them.

    **How a fork is prevented.** Not by locking. This used to take a
    ``select_for_update`` on the chain head, which did not work and could not:
    Django sends ``pre_save`` before ``save_base`` opens its write context, and
    for a model with no parents that context is ``mark_for_rollback_on_error``
    rather than a transaction. So on any caller not already inside
    ``atomic()`` — which was most of them — the lock's own transaction
    committed, releasing the row, *before* the INSERT was issued. The lock
    covered the read alone.

    Making the lock span the insert was the obvious repair and the wrong one:
    holding chain locks across a longer transaction is what produced this
    codebase's MySQL deadlocks on the upload path.

    So correctness comes from a ``UniqueConstraint`` on
    ``(chain_partition, chain_position)`` instead. Two writers that pick the
    same position no longer both succeed — one gets an ``IntegrityError`` and
    retries against the new head. A fork stops being unlikely and becomes
    impossible, no lock is held, and — because it is a constraint rather than
    a locking mode — it is enforced identically on MySQL and on SQLite, which
    means the property is finally testable in this project's own suite.
    """

    previous_hash  = models.CharField(max_length=64, blank=True, default="",
                                      help_text="event_hash of the previous row in this chain")
    event_hash     = models.CharField(max_length=64, blank=True, default="", db_index=True,
                                      help_text="SHA-256(previous_hash + payload + partition)")
    # NULL, not 0, for a row that has never been chained. WorkingPaper defers
    # chaining until sign-off, so drafts genuinely have no position — and 0
    # would both claim they do and collide with every other draft under the
    # unique constraint. NULLs do not conflict in a unique index, which is
    # exactly the behaviour an "unset" position needs.
    chain_position = models.PositiveBigIntegerField(null=True, blank=True, default=None,
                                                    db_index=True,
                                                    help_text="1-based position within this chain; NULL until chained")
    # The partition key, frozen at chain time as a plain string.
    #
    # It holds what _chain_organization_id() returned, and it is a column
    # rather than a live FK lookup for two reasons. First, every chained model
    # here partitions by organisation but reaches it differently
    # (InvoiceAuditEvent goes through invoice__organization_id), so filtering
    # and indexing were per-model and one of them needed a join. Second, the
    # organisation FKs are on_delete=SET_NULL: deleting a tenant used to null
    # the column the chain was partitioned and hashed by, which silently moved
    # that tenant's rows into the platform chain with foreign positions and
    # invalidated their hashes. A frozen copy cannot be rewritten by a delete
    # elsewhere.
    chain_partition = models.CharField(max_length=64, blank=True, default="", db_index=True,
                                       help_text="Frozen partition key (organization id) this row's chain belongs to")

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

    @classmethod
    def _chain_requires_all_rows(cls) -> bool:
        """Whether every row of this model must be chained to count as intact.

        True for append-only logs: an unchained row there is either a bug or
        someone blanking ``event_hash`` to hide an entry, and verification has
        to say so. False for models that chain on a domain trigger — a
        WorkingPaper in draft is legitimately unchained, and reporting it as a
        break would train people to ignore the report.
        """
        return False

    def _after_chain_assigned(self) -> None:
        """Hook for anything derived from `event_hash`, run before the INSERT.

        Models carrying a legacy `chain_hash` mirror populate it here. Doing it
        after save() instead — as an extra UPDATE — meant the mirror was a
        second statement outside the insert's atomic block: if it failed, the
        row was already committed while the caller saw an exception for a write
        that had in fact succeeded. Assigning the value before the insert makes
        it one statement, atomic by construction, and one round trip cheaper.
        """
        return

    def _freeze_chain_snapshot(self) -> None:
        """Copy anything mutable the payload depends on into frozen columns.

        Called once, before the row is hashed. A payload may only reference
        values that cannot change afterwards; a field reached through an FK
        with on_delete=SET_NULL is not one of those, and reading it directly
        made ordinary user and tenant deletions look like tampering. Models
        override this to snapshot such values (AuditLog copies the actor id).

        Default: nothing to freeze.
        """
        return

    @classmethod
    def _chain_unique_constraint_name(cls) -> str:
        """Name of the (chain_partition, chain_position) unique constraint.

        Used to tell "another writer took this position" apart from any other
        IntegrityError, so only the former is retried.
        """
        return f"uniq_chain_position_{cls._meta.model_name}"

    def lock_chain(self) -> None:
        """Force chain assignment now. Use when a model defers chaining via
        ``_should_chain_now``. Idempotent — once chained, this is a no-op.
        Persisting the new fields is the caller's responsibility."""
        if not self.event_hash:
            assign_chain_fields(self)

    # ── The append path ──────────────────────────────────────────────────────

    @classmethod
    def _chain_written_fields(cls) -> tuple:
        """Every column the chain machinery writes on this model.

        Detected rather than hard-coded, because a caller passing
        `update_fields` must include all of them or the chaining is computed
        and then silently thrown away. That is not hypothetical: WorkingPaper's
        partner_sign() listed previous_hash, event_hash and chain_position by
        hand, so when `chain_partition` was added every locked paper was
        written with an empty partition — landing all tenants in one partition
        and colliding on the unique constraint.
        """
        names = {"previous_hash", "event_hash", "chain_position", "chain_partition"}
        local = {f.name for f in cls._meta.local_fields}
        return tuple(sorted(names | (local & {"chain_hash", "chain_actor"})))

    def save(self, *args, **kwargs):
        """Append with retry; see the class docstring for why not a lock.

        Only a first, chainable insert goes through the retry envelope. Updates
        and already-chained rows take the plain path — re-chaining an existing
        row is precisely what must never happen. (Models that defer chaining,
        like WorkingPaper, chain on the *update* that flips them to locked, so
        that path must still persist the fields.)
        """
        will_chain = not self.event_hash and self._should_chain_now()

        if will_chain and kwargs.get("update_fields") is not None:
            # pre_save is about to assign the chain fields. A caller-supplied
            # update_fields that omits them would compute the chain and then
            # discard it on the way to the database.
            kwargs["update_fields"] = (
                set(kwargs["update_fields"]) | set(self._chain_written_fields())
            )

        chainable_insert = self._state.adding and will_chain
        if not chainable_insert:
            return super().save(*args, **kwargs)

        constraint = self._chain_unique_constraint_name()
        last_error = None

        for _ in range(CHAIN_INSERT_RETRIES):
            # Clear any assignment left by a losing attempt so the pre_save
            # signal recomputes against the *new* head. Without this the retry
            # would re-submit the position it just lost, forever.
            self.previous_hash  = ""
            self.event_hash     = ""
            self.chain_position = None

            try:
                # A savepoint, so a lost race rolls back just this insert. When
                # a caller already has a transaction open, an IntegrityError
                # would otherwise poison it and the retry could not run.
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError as exc:
                if not _is_position_conflict(exc, constraint):
                    raise           # not our race — a real integrity problem
                last_error = exc
                logger.info("[HashChain] %s lost a position race; retrying",
                            type(self).__name__)

        raise ChainContentionError(
            f"{type(self).__name__}: could not obtain a chain position after "
            f"{CHAIN_INSERT_RETRIES} attempts in partition "
            f"{self._chain_organization_id()!r}."
        ) from last_error

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
        # chain_partition, not a live _chain_organization_id() lookup. It holds
        # the identical string — assign_chain_fields writes
        # str(_chain_organization_id() or "") into it — so the hash material is
        # byte-for-byte what it was before this column existed and every
        # pre-existing chain still verifies. What changes is that the value can
        # no longer be rewritten underneath a hashed row by an unrelated
        # SET_NULL, and that verification stops needing a join to recompute it.
        partition = self.chain_partition or str(self._chain_organization_id() or "")
        payload = json.dumps(self._chain_payload(), sort_keys=True, separators=(",", ":"),
                             default=_json_default)
        material = f"{previous_hash}|{payload}|{partition}".encode("utf-8")
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

    Model = instance.__class__

    # Freeze the partition key and any model-specific snapshot before anything
    # hashes them. Order matters: compute_hash reads both.
    partition = str(instance._chain_organization_id() or "")
    instance.chain_partition = partition
    instance._freeze_chain_snapshot()

    # No lock, and no transaction of its own.
    #
    # This read is deliberately optimistic. The previous implementation took a
    # select_for_update here inside its own atomic block, which released the
    # lock at that block's commit — before the INSERT — and so serialised
    # nothing; extending the lock to cover the insert would have reintroduced
    # the upload-path deadlocks instead. The unique constraint on
    # (chain_partition, chain_position) is what actually prevents two rows
    # sharing a position, and HashChainMixin.save() retries the loser.
    previous = (
        Model.objects
        .filter(chain_partition=partition, chain_position__isnull=False)
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
    instance._after_chain_assigned()


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


def _latest_checkpoint(model_cls, partition):
    """Newest ChainCheckpoint covering this (model, partition), or None.

    Imported lazily: ChainCheckpoint is itself a HashChainMixin subclass, so a
    module-level import here would be circular. A checkpoint for the checkpoint
    chain is meaningless and is refused — retiring the record of retirements
    would be a way to launder a deletion.
    """
    from apps.audit.models import ChainCheckpoint

    if model_cls is ChainCheckpoint:
        return None

    return (
        ChainCheckpoint.objects
        .filter(target_model=model_cls.__name__, target_partition=partition)
        .order_by("-up_to_position")
        .first()
    )


def retire_chain_prefix(model_cls, partition, up_to_position, *, reason="retention"):
    """Record a checkpoint, then delete the covered rows. Returns the checkpoint.

    Order matters: the anchor is written *before* the rows go, so a crash
    half-way leaves a checkpoint claiming more than was deleted — which
    verification tolerates — rather than deleted rows with no anchor, which it
    reports as tampering forever.
    """
    from apps.audit.models import ChainCheckpoint

    if model_cls is ChainCheckpoint:
        raise ValueError("The checkpoint chain cannot itself be retired.")

    doomed = model_cls.objects.filter(
        chain_partition=partition,
        chain_position__isnull=False,
        chain_position__lte=up_to_position,
    )
    last = doomed.order_by("-chain_position").first()
    if last is None:
        return None

    checkpoint = ChainCheckpoint.objects.create(
        target_model=model_cls.__name__,
        target_partition=partition,
        up_to_position=last.chain_position,
        head_hash=last.event_hash,
        rows_removed=doomed.count(),
        reason=reason,
    )

    # _raw_delete bypasses the collector and the pre_delete signal. Both are
    # deliberate: the signal exists to warn that a deletion will break
    # verification, and here it will not — the checkpoint above accounts for
    # exactly these rows. Leaving the signal connected would also drop Django
    # out of its fast-delete path and emit one warning per row, turning a
    # single DELETE into a full table read on the retention job.
    doomed._raw_delete(doomed.db)
    return checkpoint


def verify_chain(model_cls, organization_id) -> ChainReport:
    """Walk a chain in increasing chain_position order and report any break.

    Returns a ChainReport with `is_intact=True` for an unblemished chain, or
    a list of breaks pinning the exact row that diverged.
    """
    partition = str(organization_id or "")

    # Filter on the frozen partition column rather than each model's own org
    # path. Uniform across models, index-friendly, and for InvoiceAuditEvent it
    # drops a join to invoice__organization_id.
    base = model_cls.objects.filter(chain_partition=partition)
    rows = base.filter(chain_position__isnull=False).order_by("chain_position", "pk")

    report = ChainReport(model=model_cls.__name__, organization_id=organization_id)
    expected_previous = GENESIS_HASH

    # Resume from the newest checkpoint, if a prefix of this chain has been
    # legitimately retired. Without this, the first retention purge would make
    # every remaining row report a break forever — the trail would be accusing
    # the retention policy of tampering. See ChainCheckpoint.
    checkpoint = _latest_checkpoint(model_cls, partition)
    if checkpoint is not None:
        expected_previous = checkpoint.head_hash
        rows = rows.filter(chain_position__gt=checkpoint.up_to_position)

    # A row that was never chained is skipped above, so for append-only models
    # it has to be accounted for here — otherwise blanking event_hash and
    # chain_position would be a way to drop an entry out of verification
    # entirely. Models that chain on a domain trigger (WorkingPaper drafts)
    # legitimately have unchained rows and opt out.
    if model_cls._chain_requires_all_rows():
        unchained = base.filter(chain_position__isnull=True)
        for row in unchained.iterator(chunk_size=500):
            report.is_intact = False
            report.breaks.append(ChainBreak(
                chain_position=0,
                row_id=str(row.pk),
                reason="unchained_row",
            ))

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
