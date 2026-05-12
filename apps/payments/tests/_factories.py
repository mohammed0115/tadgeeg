"""Shared test helpers — keep test setUp boilerplate small."""
from django.contrib.auth import get_user_model

from apps.authentication.models import Organization


def make_org(name="Test Org"):
    return Organization.objects.create(name=name)


def make_user(*, organization, email="user@example.com", role=None):
    User = get_user_model()
    return User.objects.create_user(
        email=email,
        password="StrongPass123!",
        full_name="Test User",
        role=role or User.Role.JUNIOR_AUDITOR,
        organization=organization,
    )
