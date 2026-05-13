"""SoD-guarded posting flow for journal entries.

Existing ``apps.ledger.services.post_entry()`` creates and immediately
posts an entry as a single user. That's fine for system-sourced entries
(invoice/payment/ZATCA/period-close), where the "user" is the platform.

For **manual** entries (Source.MANUAL), ISA 240 §32(a) and standard SoD
require a different person to authorize the posting. This module wraps
that transition:

  • ``create_draft_entry(...)``   — same as post_entry but forces
                                    post_immediately=False, returning a DRAFT.
  • ``post_with_sod(entry, by_user)``  — transitions DRAFT → POSTED with
                                         maker/checker enforcement.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.ledger.models import JournalEntry
from apps.ledger.services import post_entry
from core.audit.sod import SoDViolation, enforce_sod


def create_draft_entry(*,
                       organization,
                       entry_date: date,
                       description: str,
                       lines: list[dict],
                       reference: str = "",
                       source: str = JournalEntry.Source.MANUAL,
                       currency: str = "SAR",
                       base_currency: str = "SAR",
                       created_by=None,
                       idempotency_key: str = "") -> JournalEntry:
    """Create a balanced, validated DRAFT entry. Does not post."""
    return post_entry(
        organization=organization,
        entry_date=entry_date,
        description=description,
        lines=lines,
        reference=reference,
        source=source,
        currency=currency,
        base_currency=base_currency,
        created_by=created_by,
        idempotency_key=idempotency_key,
        post_immediately=False,
    )


@transaction.atomic
def post_with_sod(entry: JournalEntry, *, by_user) -> JournalEntry:
    """Transition a DRAFT entry to POSTED under SoD.

    Raises:
      * ``ValueError`` — entry is not in DRAFT.
      * ``SoDViolation`` — actor is the same as the creator (manual sources only).
    """
    if entry.status != JournalEntry.Status.DRAFT:
        raise ValueError(
            f"entry {entry.entry_number} is {entry.status}, not DRAFT — "
            f"cannot post"
        )

    # System-sourced entries (invoice/payment/system) skip SoD: there
    # is no human maker on the other side. Manual entries DO need
    # maker/checker separation.
    if entry.source == JournalEntry.Source.MANUAL:
        enforce_sod(
            actor=by_user,
            object_=entry,
            stage="post",
            maker_field="created_by",
        )

    entry.status    = JournalEntry.Status.POSTED
    entry.posted_at = timezone.now()
    entry.posted_by = by_user
    entry.save()
    return entry
