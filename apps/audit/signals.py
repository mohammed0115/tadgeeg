"""
Hash-chain signals — Phase 1.1 of the Enterprise Roadmap.

For every model that inherits from `HashChainMixin`, regardless of which app
defines it:

  • pre_save  on creation  → compute and assign chain fields.
  • pre_save  on update    → reject any change to the immutable payload.
  • pre_delete             → log a warning; the chain stays as-is so
                             `verify_chain()` will surface the gap.

Hooking is driven by `class_prepared` so chain models declared in apps that
load *after* `apps.audit` are still picked up — INSTALLED_APPS ordering must
not silently break the audit trail.
"""

from __future__ import annotations

import logging

from django.db.models.signals import pre_save, pre_delete, class_prepared
from django.dispatch import receiver

from apps.audit.integrity import HashChainMixin, assign_chain_fields

logger = logging.getLogger("finai")


# ─────────────────────────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────────────────────────

def _on_pre_save(sender, instance, **kwargs):
    """Assign chain fields on first save; reject mutations to existing rows."""
    if not isinstance(instance, HashChainMixin):
        return

    if instance.pk and instance.event_hash:
        # Row already chained — its payload is now immutable. We let the row
        # itself be re-saved (e.g. timestamp, related FKs) only if the
        # payload would not change. assign_chain_fields() is idempotent — it
        # short-circuits when event_hash is non-empty — so we just need to
        # block payload mutations here.
        try:
            stored = sender.objects.get(pk=instance.pk)
        except sender.DoesNotExist:
            return  # being created with a custom pk — let the rest run

        if stored.event_hash and stored.event_hash != instance.event_hash:
            from django.core.exceptions import ValidationError
            raise ValidationError(
                f"{sender.__name__} {instance.pk} is part of a tamper-evident "
                f"audit trail and cannot be re-hashed. To void this row, "
                f"append a new compensating event instead."
            )

        new_payload  = instance._chain_payload()
        prev_payload = stored._chain_payload()
        if new_payload != prev_payload:
            from django.core.exceptions import ValidationError
            raise ValidationError(
                f"{sender.__name__} {instance.pk} is locked by the audit "
                f"hash chain — its payload fields cannot be edited after "
                f"the row has been chained."
            )
        return

    # First save: assign chain fields, but only if the model wants it.
    # Models like WorkingPaper override _should_chain_now() to return False
    # until a domain trigger (e.g. partner sign-off) flips them to LOCKED.
    if not instance.event_hash and instance._should_chain_now():
        try:
            assign_chain_fields(instance)
        except Exception as exc:
            # Never silently fail — audit-trail integrity is the whole point.
            logger.error("[HashChain] %s pre_save failed: %s", sender.__name__, exc)
            raise


def _on_pre_delete(sender, instance, **kwargs):
    """Log deletes; the chain stays referencing the previous_hash either way."""
    if not isinstance(instance, HashChainMixin):
        return
    logger.warning(
        "[HashChain] DELETE %s pk=%s position=%s — verify_chain() will report "
        "a missing row at this position from now on.",
        sender.__name__, instance.pk, instance.chain_position,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────────────

def _connect(model_cls):
    pre_save.connect(
        _on_pre_save, sender=model_cls, weak=False,
        dispatch_uid=f"hashchain.pre_save.{model_cls.__module__}.{model_cls.__name__}",
    )
    pre_delete.connect(
        _on_pre_delete, sender=model_cls, weak=False,
        dispatch_uid=f"hashchain.pre_delete.{model_cls.__module__}.{model_cls.__name__}",
    )


def _on_class_prepared(sender, **kwargs):
    """Wire chain-mixin subclasses as their classes finish preparation."""
    if not (isinstance(sender, type) and issubclass(sender, HashChainMixin)):
        return
    if getattr(sender._meta, "abstract", False):
        return
    _connect(sender)
    logger.info("[HashChain] Hooked %s.%s", sender.__module__, sender.__name__)


class_prepared.connect(_on_class_prepared, weak=False,
                       dispatch_uid="hashchain.class_prepared")


# Also connect any subclass already loaded by the time this module is imported
# — class_prepared has already fired for them.
def _connect_existing_subclasses():
    stack = list(HashChainMixin.__subclasses__())
    while stack:
        cls = stack.pop()
        if getattr(cls._meta, "abstract", False):
            stack.extend(cls.__subclasses__())
            continue
        _connect(cls)
        stack.extend(cls.__subclasses__())


_connect_existing_subclasses()
