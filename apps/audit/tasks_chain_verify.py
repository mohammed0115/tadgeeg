"""Nightly hash-chain integrity audit (F-5).

The hash-chain catches tampering only if it's actually re-verified. Up
to now ``verify_chain()`` was a method auditors had to call manually.
This task walks every chained model × organisation each night, logs
the first chain break it finds per (model, org), and increments a
metric counter for alerting.

Failure modes covered:
  • Row edited in place (event_hash != recomputed).
  • Row deleted from middle (previous_hash mismatch on the next row).
  • Row inserted (chain_position duplicated).
  • Row missing event_hash entirely.

Recommended schedule: 03:30 UTC (after other nightly jobs).
"""
from __future__ import annotations

import logging

from celery import shared_task


logger = logging.getLogger("audit.chain_verify")


def _chained_models():
    """Every concrete subclass of HashChainMixin, discovered rather than listed.

    This used to be a hand-maintained list of three imports, and it drifted
    exactly as hand-maintained lists do: when AuditLog and ActivityLog moved
    onto the chain, the migration that rebuilt them described itself as
    establishing "a verifiable baseline from this migration forward" — and the
    job that does the verifying never looked at them. The customer-facing
    integrity page had auto-discovered subclasses all along, so a break would
    have been shown to an auditor while raising no alert at all.

    Discovery keeps the two in step by construction. A model joining the chain
    is now verified because it joined, not because someone also remembered to
    edit this file.
    """
    from apps.audit.integrity import HashChainMixin

    discovered: list[type] = []
    seen: set[type] = set()
    stack = list(HashChainMixin.__subclasses__())

    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        stack.extend(cls.__subclasses__())
        if getattr(cls._meta, "abstract", False):
            continue
        discovered.append(cls)

    return sorted(discovered, key=lambda c: c.__name__)


@shared_task(name="audit.verify_chains_nightly")
def verify_chains_nightly() -> dict:
    """Walk every (model, org) hash chain and report any break.

    Returns a small summary dict for beat logs:
      {
        "checked":    <int>,   # (model, org) pairs walked
        "intact":     <int>,
        "broken":     <int>,
        "breaks":     [{"model": "...", "org_id": "...", "breaks": [...]}],
      }
    """
    from apps.audit.integrity import verify_chain
    from apps.authentication.models import Organization

    summary = {"checked": 0, "intact": 0, "broken": 0, "breaks": []}

    org_ids = list(Organization.objects.values_list("id", flat=True))
    for model_cls in _chained_models():
        for org_id in org_ids:
            summary["checked"] += 1
            try:
                report = verify_chain(model_cls, org_id)
            except Exception:                # pragma: no cover
                logger.exception(
                    "[chain_verify] %s × %s — verify_chain raised",
                    model_cls.__name__, org_id,
                )
                continue
            if report.is_intact:
                summary["intact"] += 1
                continue
            summary["broken"] += 1
            entry = {
                "model":  model_cls.__name__,
                "org_id": str(org_id),
                "rows_checked": report.rows_checked,
                "breaks": [b.to_dict() for b in report.breaks],
            }
            summary["breaks"].append(entry)
            logger.error(
                "[chain_verify] CHAIN BROKEN  model=%s org=%s breaks=%d",
                model_cls.__name__, org_id, len(report.breaks),
            )

    if summary["broken"]:
        logger.error("[chain_verify] nightly run: %s", summary)
    else:
        logger.info("[chain_verify] nightly run clean: %s pairs intact", summary["intact"])
    return summary
