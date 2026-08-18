"""Provider-agnostic WhatsApp template delivery.

The application never claims WhatsApp availability merely because code exists:
provider credentials, an approved template, an enabled organisation preference,
and a package entitlement are all required before a request can be made.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import requests
from django.conf import settings


class WhatsAppUnavailable(RuntimeError):
    pass


class WhatsAppDeliveryError(RuntimeError):
    pass


_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


@dataclass(frozen=True)
class WhatsAppTemplate:
    name: str
    language: str = "ar"
    components: tuple[dict, ...] = ()


def validate_recipient(phone: str) -> str:
    phone = (phone or "").strip().replace(" ", "")
    if not _E164.fullmatch(phone):
        raise WhatsAppUnavailable("WhatsApp recipient must be an E.164 phone number.")
    return phone


def _meta_config() -> tuple[str, str]:
    token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "")
    phone_number_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "")
    if not token or not phone_number_id:
        raise WhatsAppUnavailable("WhatsApp provider is not configured or approved.")
    return token, phone_number_id


def send_template(*, to: str, template: WhatsAppTemplate) -> dict:
    """Send one pre-approved template through Meta Graph API.

    This method deliberately has no free-form fallback: business-initiated
    WhatsApp messages must use an approved template, and a missing approval is
    an operational error rather than a reason to silently send arbitrary text.
    """
    token, phone_number_id = _meta_config()
    recipient = validate_recipient(to)
    url = f"https://graph.facebook.com/{getattr(settings, 'WHATSAPP_GRAPH_VERSION', 'v20.0')}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient.lstrip("+"),
        "type": "template",
        "template": {
            "name": template.name,
            "language": {"code": template.language},
            "components": list(template.components),
        },
    }
    # The timeout is explicit below; its value remains deployment-configurable.
    response = requests.post(  # nosec B113
        url,
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=getattr(settings, "WHATSAPP_TIMEOUT", 10),
    )
    if not response.ok:
        raise WhatsAppDeliveryError(f"WhatsApp provider rejected template: {response.status_code}")
    return response.json()


def organization_whatsapp_enabled(organization) -> bool:
    """Require both an included package feature and a saved opt-in."""
    from apps.authentication.models import OrganizationSettings
    from apps.billing.services.features import feature_decision

    if not feature_decision(organization, "whatsapp").enabled:
        return False
    preferences = (OrganizationSettings.objects.filter(organization=organization)
                   .values_list("notifications", flat=True).first() or {})
    whatsapp = preferences.get("whatsapp", {}) if isinstance(preferences, dict) else {}
    return bool(whatsapp.get("enabled") and whatsapp.get("template_alerts"))
