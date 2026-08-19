from __future__ import annotations

import pytest
from django.urls import reverse

from apps.activity_logs.models import ActivityLog
from apps.cms.models import PlatformSetting


SETTINGS_URL = "platform_admin:crm:whatsapp_business_number_update"
DASHBOARD_URL = "platform_admin:crm:dashboard"


def _setting() -> PlatformSetting:
    return PlatformSetting.objects.get(key="whatsapp_business_number")


@pytest.mark.django_db
def test_platform_owner_can_update_e164_business_number_with_audit(client, owner_user):
    setting = _setting()
    setting.value = "+966500000000"
    setting.save(update_fields=["value"])
    client.force_login(owner_user)

    response = client.post(reverse(SETTINGS_URL), {"business_number": "+966501234567"})

    assert response.status_code == 302
    setting.refresh_from_db()
    assert setting.value == "+966501234567"
    assert setting.updated_by == owner_user
    event = ActivityLog.objects.get(
        action=ActivityLog.Action.POLICY_CHANGED,
        entity_type="PlatformSetting",
        entity_id=str(setting.pk),
    )
    assert event.metadata == {
        "key": "whatsapp_business_number",
        "old_value": "+966500000000",
        "new_value": "+966501234567",
    }


@pytest.mark.django_db
def test_platform_admin_can_update_but_finance_and_support_cannot(client, admin_user, finance_user, support_user):
    client.force_login(admin_user)
    assert client.post(reverse(SETTINGS_URL), {"business_number": "+966501234567"}).status_code == 302

    for user in (finance_user, support_user):
        client.force_login(user)
        assert client.post(reverse(SETTINGS_URL), {"business_number": "+966509999999"}).status_code == 403


@pytest.mark.django_db
def test_invalid_number_is_rejected_without_change_or_audit(client, owner_user):
    setting = _setting()
    original = setting.value
    client.force_login(owner_user)

    response = client.post(reverse(SETTINGS_URL), {"business_number": "0501234567"})

    assert response.status_code == 302
    setting.refresh_from_db()
    assert setting.value == original
    assert not ActivityLog.objects.filter(
        action=ActivityLog.Action.POLICY_CHANGED,
        entity_type="PlatformSetting",
        entity_id=str(setting.pk),
    ).exists()


@pytest.mark.django_db
def test_number_form_is_visible_only_to_platform_contact_administrators(client, owner_user, admin_user, finance_user, support_user):
    for user in (owner_user, admin_user):
        client.force_login(user)
        assert 'name="business_number"' in client.get(reverse(DASHBOARD_URL)).content.decode()
    for user in (finance_user, support_user):
        client.force_login(user)
        assert 'name="business_number"' not in client.get(reverse(DASHBOARD_URL)).content.decode()


@pytest.mark.django_db
def test_get_to_setting_update_is_not_allowed(client, owner_user):
    client.force_login(owner_user)
    assert client.get(reverse(SETTINGS_URL)).status_code == 405
