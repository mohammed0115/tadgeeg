"""Generic Segregation-of-Duties enforcement (F-1).

Extends the invoice-specific ``apps.invoices.services.sod_service``
pattern to ANY business object that holds a Maker + Checker + Approver
trio. The audit-review Finding 1 flagged that SoD was invoice-only;
this module is the reusable foundation for siblings: payment refunds,
journal entries, vendor profile edits, user role changes.

Usage:
    from core.audit.sod import enforce_sod, SoDViolation

    @transaction.atomic
    def refund_payment(transaction, by_user):
        enforce_sod(
            actor=by_user,
            object_=transaction,
            stage="approve",
            maker_field="created_by",     # which FK on `transaction`
                                          # holds the maker
            checker_field=None,           # no checker for refunds
        )
        ...
"""
from __future__ import annotations

import logging
from typing import Optional

from django.utils.translation import gettext as _


logger = logging.getLogger("audit.sod")


class SoDViolation(PermissionError):
    """Raised when an action would have the same user wear two roles."""

    def __init__(self, *, stage: str, conflicts_with: str, actor_id: str = ""):
        self.stage = stage                        # "review" | "approve" | "post"
        self.conflicts_with = conflicts_with      # "maker" | "checker"
        self.actor_id = actor_id
        super().__init__(self.user_message)

    @property
    def user_message(self) -> str:
        if self.conflicts_with == "maker":
            return str(_(
                "Segregation of Duties: the user who created this record "
                "cannot also %(stage)s it."
            )) % {"stage": self.stage}
        if self.conflicts_with == "checker":
            return str(_(
                "Segregation of Duties: the reviewer cannot also approve."
            ))
        return str(_("Segregation of Duties violated."))


def enforce_sod(
    *,
    actor,
    object_,
    stage: str,
    maker_field: str = "created_by",
    checker_field: Optional[str] = None,
) -> None:
    """Raise SoDViolation if the actor wears another role on the object.

    Parameters
    ----------
    actor : User instance attempting the action.
    object_ : the business object (Invoice / PaymentTransaction / JournalEntry).
    stage : "review" or "approve" or "post" — the action being attempted.
    maker_field : attribute on object_ holding the user-FK that created it
                  (default ``created_by``; pass ``"uploaded_by"`` for documents).
    checker_field : attribute on object_ holding the reviewer's FK, or None
                    if the object doesn't have a review stage.

    The function is generic enough to drop into a decorator if a domain
    needs that level of sugar; for now, callers invoke directly so the
    error path is explicit at the API layer.
    """
    if actor is None or not getattr(actor, "is_authenticated", False):
        raise SoDViolation(stage=stage, conflicts_with="maker")

    maker_id = getattr(object_, f"{maker_field}_id", None)
    if maker_id is None:
        # The maker field may be set as the instance, not the id (when
        # the FK is freshly assigned but not yet saved).
        maker = getattr(object_, maker_field, None)
        maker_id = getattr(maker, "pk", None)

    if maker_id and actor.pk == maker_id:
        logger.warning(
            "[SoD] %s blocked: actor=%s == maker on %s pk=%s",
            stage, actor.pk, type(object_).__name__, object_.pk,
        )
        raise SoDViolation(
            stage=stage, conflicts_with="maker", actor_id=str(actor.pk),
        )

    if stage == "approve" and checker_field:
        checker_id = getattr(object_, f"{checker_field}_id", None)
        if checker_id and actor.pk == checker_id:
            logger.warning(
                "[SoD] approve blocked: actor=%s == checker on %s pk=%s",
                actor.pk, type(object_).__name__, object_.pk,
            )
            raise SoDViolation(
                stage="approve", conflicts_with="checker",
                actor_id=str(actor.pk),
            )
