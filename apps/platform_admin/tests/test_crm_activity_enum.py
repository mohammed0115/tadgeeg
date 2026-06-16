"""CRM-1F-TD-A — CustomerActivity financial action types are canonical enum members.

These tests lock the contract that the financial ``ActivityType`` members carry
the *exact* string values previously recorded as hand-written literals. They are
a regression guard: if anyone renames a value, the stored DB value would change
and existing rows / dashboards would silently diverge — these tests fail first.
"""

from apps.platform_admin.models import CustomerActivity

ActivityType = CustomerActivity.ActivityType


# The six financial operations and the value each MUST keep (pre-CRM-1F-TD-A
# literals from crm_operations.py). Do not change these strings.
FINANCIAL_ACTIVITY_VALUES = {
    "SUBSCRIPTION_EXTENDED": "subscription_extended",
    "CUSTOMER_SUSPENDED": "customer_suspended",
    "CUSTOMER_REACTIVATED": "customer_reactivated",
    "MANUAL_PAYMENT_ADDED": "manual_payment_added",
    "MANUAL_PAYMENT_CONFIRMED": "manual_payment_confirmed",
    "MANUAL_PAYMENT_REJECTED": "manual_payment_rejected",
}


def test_financial_members_keep_their_literal_values():
    for member_name, expected_value in FINANCIAL_ACTIVITY_VALUES.items():
        member = getattr(ActivityType, member_name)
        assert member.value == expected_value


def test_financial_values_are_registered_choices():
    for expected_value in FINANCIAL_ACTIVITY_VALUES.values():
        assert expected_value in ActivityType.values


def test_financial_values_fit_field_max_length():
    max_length = CustomerActivity._meta.get_field("activity_type").max_length
    for expected_value in FINANCIAL_ACTIVITY_VALUES.values():
        assert len(expected_value) <= max_length
