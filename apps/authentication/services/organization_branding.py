from __future__ import annotations

from apps.billing.services.features import require_feature
from apps.authentication.models import OrganizationSettings


class BrandingError(PermissionError):
    pass


def update_enterprise_branding(*, organization, branding: dict, report_preferences: dict | None = None):
    """Persist a tightly scoped enterprise White Label configuration."""
    require_feature(organization, "white_label")
    allowed_branding = {key: value for key, value in dict(branding or {}).items() if key in {"display_name", "logo_url", "primary_color", "support_email"}}
    if allowed_branding.get("logo_url", "") and not str(allowed_branding["logo_url"]).startswith("https://"):
        raise BrandingError("White Label logo URLs must use HTTPS.")
    settings, _ = OrganizationSettings.objects.get_or_create(organization=organization)
    settings.branding = allowed_branding
    if report_preferences is not None:
        settings.report_preferences = {key: value for key, value in dict(report_preferences).items() if key in {"include_logo", "include_cover_page", "language"}}
        settings.save(update_fields=["branding", "report_preferences", "updated_at"])
    else:
        settings.save(update_fields=["branding", "updated_at"])
    return settings
