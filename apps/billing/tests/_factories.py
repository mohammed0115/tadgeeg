"""Shared helpers for billing tests."""
from django.contrib.auth import get_user_model

from apps.authentication.models import Organization


def make_org(name="Billing Test Org"):
    return Organization.objects.create(name=name)


def make_user(*, organization, email="user@example.com"):
    User = get_user_model()
    return User.objects.create_user(
        email=email,
        password="StrongPass123!",
        full_name="Test User",
        role=User.Role.ADMIN,
        organization=organization,
    )
