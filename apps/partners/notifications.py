"""Decision emails for partner applications (§F).

Ordering with the transaction
-----------------------------
Sending is scheduled with ``transaction.on_commit`` in
``apps.partners.services``, so mail is attempted **only after the status change
is durable**. Two consequences, both deliberate:

* A mail failure cannot roll back a decision. An SMTP outage costs a
  notification, never the reviewer's approval.
* A recipient never receives "you were approved" for a transition that was then
  rolled back, because the mail is not queued until the commit succeeded.

The alternative — sending inside the transaction — trades a lost notification
for a lost decision, or for a notification about something that never happened.
Both are worse.

What is NOT in outbound mail
----------------------------
No internal notes, no reviewer identity, no rejection_reason, no application id,
no system detail. The applicant learns the outcome and how to follow up; the
review record stays internal. ``rejection_reason`` in particular is written by
staff for staff and is often blunt.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.translation import gettext as _

logger = logging.getLogger("partners.notifications")


def _plain_body(kind: str, company_name: str) -> str:
    if kind == "approved":
        return _(
            "Hello %(company)s,\n\n"
            "Thank you for applying to the Tadgeeg partner programme. We are "
            "pleased to let you know that your application has been approved.\n\n"
            "Our partnerships team will contact you shortly with the next steps.\n\n"
            "— The Tadgeeg team"
        ) % {"company": company_name}

    return _(
        "Hello %(company)s,\n\n"
        "Thank you for your interest in the Tadgeeg partner programme, and for "
        "the time you spent on your application.\n\n"
        "After review, we are not able to proceed with a partnership at this "
        "time. You are welcome to apply again in the future.\n\n"
        "— The Tadgeeg team"
    ) % {"company": company_name}


def send_application_decision(kind: str, application) -> bool:
    """Send the approval or rejection email. Returns True if it was sent.

    Never raises for a delivery problem — the caller wraps this anyway, and a
    decision email is not worth a 500 on an operator's screen after the
    decision itself has already been recorded.
    """
    if kind not in ("approved", "rejected"):
        raise ValueError(f"unknown decision kind: {kind!r}")

    recipient = (application.email or "").strip()
    if not recipient:
        logger.warning("Application %s has no email address; nothing sent.", application.pk)
        return False

    subject = (
        _("Your Tadgeeg partnership application has been approved")
        if kind == "approved"
        else _("Update on your Tadgeeg partnership application")
    )
    body = _plain_body(kind, application.company_name)

    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=[recipient],
    )
    try:
        message.send(fail_silently=False)
    except Exception:                                    # noqa: BLE001
        logger.exception("Could not send %s email to %s", kind, recipient)
        return False

    logger.info("Sent %s email for application %s", kind, application.pk)
    return True
