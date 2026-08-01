"""Partner state transitions — the audited ones.

Publish and hide change what the public sees, so both are recorded through
``log_crm_action``: the same hash-chained ``authentication.AuditLog`` path
Phase 1's trial conversion uses. There is deliberately no second audit
mechanism in this codebase.

Ordinary content edits (description, website, logo) are not audited here — they
go through the serializer and are visible in the record itself. It is the
*visibility* decision that needs a name and a timestamp attached.
"""

from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.platform_admin.services.crm_audit import log_crm_action
from core.permissions import is_platform_user

from django.utils import timezone

from .models import ApplicationStatus, Partner, PartnerStatus

logger = logging.getLogger("partners.services")

ACTION_PUBLISHED = "partner_published"
ACTION_HIDDEN = "partner_hidden"


class PartnerVisibilityError(Exception):
    """The partner could not be found."""


def _client_ip(request):
    if request is None:
        return None
    from core.utils.coerce import get_client_ip

    return get_client_ip(request) or None


def _audit(*, actor, partner, action_type, before, request):
    """Write the visibility change to the hash-chained AuditLog.

    ``organization=None`` — a partner is not a tenant. The CRM audit writer
    accepts that, and the partner is identified by resource_id plus the
    metadata below.
    """
    log_crm_action(
        actor=actor,
        organization=None,
        action_type=action_type,
        resource_type="partner",
        resource_id=str(partner.id),
        old_value={"status": before["status"], "published_at": before["published_at"]},
        new_value={
            "status": partner.status,
            "published_at": partner.published_at.isoformat() if partner.published_at else None,
        },
        metadata={
            "company_name": partner.company_name,
            "slug": partner.slug,
            "partner_tier": partner.partner_tier,
            "partner_type": partner.partner_type,
        },
        ip_address=_client_ip(request),
        record_activity=False,
    )


def _snapshot(partner):
    return {
        "status": partner.status,
        "published_at": partner.published_at.isoformat() if partner.published_at else None,
    }


def _load(pk):
    try:
        return Partner.objects.get(pk=pk)
    except (Partner.DoesNotExist, ValidationError, ValueError) as exc:
        raise PartnerVisibilityError("Partner not found.") from exc


@transaction.atomic
def publish_partner(*, pk, actor, request=None):
    """Make a partner publicly visible. Idempotent."""
    if not is_platform_user(actor):
        raise PermissionDenied("Platform staff access is required.")

    partner = _load(pk)
    before = _snapshot(partner)

    partner.publish()
    _audit(actor=actor, partner=partner, action_type=ACTION_PUBLISHED,
           before=before, request=request)

    logger.info("Partner published: %s (%s) by %s",
                partner.slug, partner.id, getattr(actor, "pk", None))
    return partner


@transaction.atomic
def hide_partner(*, pk, actor, request=None):
    """Remove a partner from public surfaces. Idempotent.

    ``published_at`` is preserved — knowing when a partner was first announced
    stays useful after they are hidden.
    """
    if not is_platform_user(actor):
        raise PermissionDenied("Platform staff access is required.")

    partner = _load(pk)
    before = _snapshot(partner)

    partner.hide()
    _audit(actor=actor, partner=partner, action_type=ACTION_HIDDEN,
           before=before, request=request)

    logger.info("Partner hidden: %s (%s) by %s",
                partner.slug, partner.id, getattr(actor, "pk", None))
    return partner


@transaction.atomic
def reorder_partners(entries) -> int:
    """Set ``display_order`` for several partners.

    ``entries`` is ``[{"id": ..., "display_order": int}, ...]``. Unknown ids are
    skipped rather than failing the whole batch — a stale row in the admin UI
    should not block reordering the rest.
    """
    updated = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValidationError("each order entry must be an object")
        partner_id = entry.get("id")
        order = entry.get("display_order")
        if partner_id is None or order is None:
            raise ValidationError("each order entry needs id and display_order")
        if isinstance(order, bool) or not isinstance(order, int) or order < 0:
            raise ValidationError("display_order must be a non-negative integer")

        matched = Partner.objects.filter(pk=partner_id).update(display_order=order)
        updated += matched
    return updated


# ─── Application review workflow (Phase 2B, §E.7) ────────────────────────────

ACTION_APP_SUBMITTED = "partner_application_submitted"
ACTION_APP_UNDER_REVIEW = "partner_application_under_review"
ACTION_APP_APPROVED = "partner_application_approved"
ACTION_APP_REJECTED = "partner_application_rejected"

#: Legal transitions. Anything absent is refused at the SERVICE layer, so a
#: hand-crafted API call cannot do what the UI won't offer. Approved and
#: Rejected are terminal: re-opening a decided application would need a real
#: domain reason and its own audit semantics, and §E.7 defines neither.
_LEGAL_TRANSITIONS = {
    ApplicationStatus.SUBMITTED: {
        ApplicationStatus.UNDER_REVIEW,
        ApplicationStatus.APPROVED,
        ApplicationStatus.REJECTED,
    },
    ApplicationStatus.UNDER_REVIEW: {
        ApplicationStatus.APPROVED,
        ApplicationStatus.REJECTED,
    },
    ApplicationStatus.APPROVED: set(),
    ApplicationStatus.REJECTED: set(),
}


class ApplicationTransitionError(Exception):
    """The requested transition is not legal from the current state."""


def _load_application(pk):
    from .models import PartnerApplication

    try:
        return PartnerApplication.objects.get(pk=pk)
    except (PartnerApplication.DoesNotExist, ValidationError, ValueError) as exc:
        raise PartnerVisibilityError("Application not found.") from exc


def _assert_transition(application, target):
    allowed = _LEGAL_TRANSITIONS.get(application.status, set())
    if target not in allowed:
        raise ApplicationTransitionError(
            f"Cannot move an application from {application.status!r} to {target!r}. "
            f"Allowed from here: {sorted(allowed) or 'none (terminal state)'}."
        )


def _audit_application(*, actor, application, action_type, before, request, extra=None):
    metadata = {
        "company_name": application.company_name,
        "email": application.email,
        "requested_partner_type": application.requested_partner_type,
    }
    if extra:
        metadata.update(extra)

    log_crm_action(
        actor=actor,
        organization=None,
        action_type=action_type,
        resource_type="partner_application",
        resource_id=str(application.id),
        old_value={"status": before},
        new_value={"status": application.status},
        metadata=metadata,
        ip_address=_client_ip(request),
        record_activity=False,
    )


@transaction.atomic
def start_review(*, pk, actor, request=None):
    """Submitted → Under Review."""
    if not is_platform_user(actor):
        raise PermissionDenied("Platform staff access is required.")

    application = _load_application(pk)
    before = application.status
    _assert_transition(application, ApplicationStatus.UNDER_REVIEW)

    application.status = ApplicationStatus.UNDER_REVIEW
    application.reviewed_by = actor
    application.save(update_fields=["status", "reviewed_by", "updated_at"])

    _audit_application(actor=actor, application=application,
                       action_type=ACTION_APP_UNDER_REVIEW, before=before, request=request)
    return application


@transaction.atomic
def approve_application(*, pk, actor, partner_tier, partner_type=None, request=None):
    """Approve, and create the Partner record.

    ``partner_tier`` is REQUIRED (decision D3). Phase 2A established that the
    public page groups by tier plus one type-keyed section, so an approved
    partner with no tier and a Technical/Training type appears in **no**
    section — accepted, invisible, and nobody notices. Requiring the reviewer
    to choose a tier closes that hole without inventing a fifth section the
    approved design does not have.

    The new Partner is created as DRAFT, not published: approval is a
    commercial decision, publication is an editorial one, and they are made by
    different people at different times. Publishing stays the audited action
    Phase 2A built.
    """
    from .models import Partner, PartnerTier

    if not is_platform_user(actor):
        raise PermissionDenied("Platform staff access is required.")

    application = _load_application(pk)
    before = application.status
    _assert_transition(application, ApplicationStatus.APPROVED)

    tier = (partner_tier or "").strip()
    if tier not in PartnerTier.values:
        raise ValidationError(
            "A partner tier is required to approve an application. Without one "
            "the partner would appear in no section of the public page. "
            f"Valid tiers: {', '.join(PartnerTier.values)}."
        )

    resolved_type = (partner_type or application.requested_partner_type or "").strip()

    partner = Partner.objects.create(
        company_name=application.company_name,
        slug=_unique_slug(application.company_name),
        country=application.country,
        short_description=(application.company_summary or "")[:300],
        long_description=application.company_summary or "",
        website=application.website or "",
        partner_type=resolved_type,
        partner_tier=tier,
        status=PartnerStatus.DRAFT,
        contact_email=application.email,
        contact_phone=application.mobile,
        source_application=application,
    )

    application.status = ApplicationStatus.APPROVED
    application.reviewed_by = actor
    application.reviewed_at = timezone.now()
    application.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])

    _audit_application(
        actor=actor, application=application, action_type=ACTION_APP_APPROVED,
        before=before, request=request,
        extra={"partner_id": str(partner.id), "partner_tier": tier, "partner_type": resolved_type},
    )

    # Email AFTER the transition is durable — see notifications.py for the
    # ordering rationale. A mail failure must never lose the decision.
    transaction.on_commit(lambda: _notify_safely("approved", application))
    return application, partner


@transaction.atomic
def reject_application(*, pk, actor, reason="", request=None):
    """Reject, with an optional internal reason."""
    if not is_platform_user(actor):
        raise PermissionDenied("Platform staff access is required.")

    application = _load_application(pk)
    before = application.status
    _assert_transition(application, ApplicationStatus.REJECTED)

    application.status = ApplicationStatus.REJECTED
    application.reviewed_by = actor
    application.reviewed_at = timezone.now()
    application.rejection_reason = (reason or "").strip()
    application.save(update_fields=[
        "status", "reviewed_by", "reviewed_at", "rejection_reason", "updated_at",
    ])

    _audit_application(actor=actor, application=application,
                       action_type=ACTION_APP_REJECTED, before=before, request=request)

    transaction.on_commit(lambda: _notify_safely("rejected", application))
    return application


def add_note(*, pk, actor, note):
    """Internal reviewer note. Never served publicly."""
    from .models import PartnerApplicationNote

    if not is_platform_user(actor):
        raise PermissionDenied("Platform staff access is required.")
    text = (note or "").strip()
    if not text:
        raise ValidationError("A note cannot be empty.")

    application = _load_application(pk)
    return PartnerApplicationNote.objects.create(
        application=application, author=actor, note=text,
    )


def _unique_slug(company_name):
    from django.utils.text import slugify

    from .models import Partner

    base = slugify(company_name) or "partner"
    candidate, counter = base, 2
    while Partner.objects.filter(slug=candidate).exists():
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def _notify_safely(kind, application):
    """Send the decision email without letting a mail failure matter.

    Called from transaction.on_commit, so the status change is already durable
    before this runs: mail cannot roll it back, and an SMTP outage costs a
    notification, never a decision.
    """
    from .notifications import send_application_decision

    try:
        send_application_decision(kind, application)
    except Exception:                                    # noqa: BLE001
        logger.exception(
            "Failed to send %s email for application %s — the decision itself stands.",
            kind, application.pk,
        )
