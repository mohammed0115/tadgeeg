"""Platform-wide public contact configuration managed from CRM."""
from __future__ import annotations

from apps.activity_logs.models import ActivityLog
from apps.activity_logs.service import ActivityLogService
from apps.cms.models import PlatformSetting


class PlatformContactSettingMissing(RuntimeError):
    """Raised when the deployment has not applied the setting seed migration."""


def update_whatsapp_business_number(*, number: str, user, request=None) -> bool:
    """Persist the public E.164 contact number and append an audit event.

    The setting is deliberately distinct from Meta's phone-number ID and access
    token, both of which remain deployment secrets. Returns ``True`` only when
    the persisted value changed.
    """
    setting = PlatformSetting.objects.filter(key="whatsapp_business_number").first()
    if setting is None:
        raise PlatformContactSettingMissing("WhatsApp Business setting is not configured.")

    previous_value = setting.value
    if previous_value == number:
        return False

    setting.value = number
    setting.updated_by = user
    setting.save(update_fields=["value", "updated_by", "updated_at"])
    ActivityLogService.log(
        action=ActivityLog.Action.POLICY_CHANGED,
        user=user,
        entity_type="PlatformSetting",
        entity_id=str(setting.pk),
        description="WhatsApp Business public contact number updated.",
        metadata={
            "key": setting.key,
            "old_value": previous_value,
            "new_value": number,
        },
        request=request,
    )
    return True
