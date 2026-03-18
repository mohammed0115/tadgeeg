"""Helpers for self-serve tenant bootstrapping."""

from __future__ import annotations

import re

from apps.authentication.models import Organization, OrganizationSettings, User


DEFAULT_FINANCIAL_SETTINGS = {
    "monthly_budget_limit": 0,
    "large_invoice_threshold": 10000,
    "vat_rate": 15.0,
    "anomaly_threshold_pct": 25,
    "max_daily_invoices": 100,
    "expense_policy_limit": 5000,
    "zatca_api_url": "",
    "zatca_env": "sandbox",
    "zatca_qr_required": "true",
    "ai_review_mode": "balanced",
    "ai_confidence_threshold": 85,
    "ai_require_explanations": True,
    "ai_auto_create_case": True,
    "ai_block_high_risk_invoices": False,
    "invoice_due_days": 30,
    "invoice_require_po": True,
    "invoice_require_vendor_vat": True,
    "invoice_rounding_policy": "standard",
    "invoice_default_notes": "",
    "compliance_hold_missing_tax_id": True,
}


DEFAULT_NOTIFICATION_SETTINGS = {
    "email_invoice_flagged": True,
    "email_audit_case_created": True,
    "email_weekly_summary": True,
    "email_vat_late_filing": True,
    "ws_realtime_alerts": True,
    "payroll_anomaly_alert": True,
}


COUNTRY_CURRENCY_MAP = {
    Organization.Country.SAUDI_ARABIA: Organization.Currency.SAR,
    Organization.Country.UAE: Organization.Currency.AED,
    Organization.Country.BAHRAIN: Organization.Currency.BHD,
    Organization.Country.KUWAIT: Organization.Currency.KWD,
    Organization.Country.OMAN: Organization.Currency.OMR,
    Organization.Country.QATAR: Organization.Currency.QAR,
}


def derive_organization_name(*, email: str, full_name: str = "", organization_name: str = "") -> str:
    seed = (organization_name or full_name or email.split("@")[0] or "New User").strip()
    seed = re.sub(r"[_\-.]+", " ", seed)
    seed = re.sub(r"\s+", " ", seed).strip()
    if seed.isascii():
        seed = seed.title()
    return seed or "New User"


def ensure_organization_settings(organization: Organization) -> OrganizationSettings:
    financial_defaults = dict(DEFAULT_FINANCIAL_SETTINGS)
    financial_defaults["vat_rate"] = float(organization.vat_rate or 15)
    settings_obj, created = OrganizationSettings.objects.get_or_create(
        organization=organization,
        defaults={
            "financial": financial_defaults,
            "notifications": dict(DEFAULT_NOTIFICATION_SETTINGS),
        },
    )
    if created:
        return settings_obj

    dirty = False
    if not isinstance(settings_obj.financial, dict) or not settings_obj.financial:
        settings_obj.financial = financial_defaults
        dirty = True
    if not isinstance(settings_obj.notifications, dict) or not settings_obj.notifications:
        settings_obj.notifications = dict(DEFAULT_NOTIFICATION_SETTINGS)
        dirty = True
    if dirty:
        settings_obj.save(update_fields=["financial", "notifications", "updated_at"])
    return settings_obj


def ensure_user_organization(
    user: User,
    *,
    organization_name: str = "",
    country: str = Organization.Country.SAUDI_ARABIA,
    promote_owner: bool = True,
) -> Organization:
    if user.organization_id:
        organization = user.organization
    else:
        safe_country = country if country in Organization.Country.values else Organization.Country.SAUDI_ARABIA
        organization = Organization.objects.create(
            name=derive_organization_name(
                email=user.email,
                full_name=user.full_name,
                organization_name=organization_name,
            ),
            name_ar=organization_name or "",
            country=safe_country,
            currency=COUNTRY_CURRENCY_MAP.get(safe_country, Organization.Currency.SAR),
            vat_rate=15,
        )
        update_fields = ["organization"]
        user.organization = organization
        if promote_owner and user.role != User.Role.ADMIN:
            user.role = User.Role.ADMIN
            update_fields.append("role")
        user.save(update_fields=update_fields)

    ensure_organization_settings(organization)
    return organization
