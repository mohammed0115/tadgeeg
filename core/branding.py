"""Central branding helpers for Tadgeeg AI."""

from __future__ import annotations

from django.conf import settings


def get_branding_context(language: str | None = None) -> dict:
    lang_code = (language or getattr(settings, "LANGUAGE_CODE", "ar") or "ar").split("-")[0]
    is_arabic = lang_code == "ar"

    product_name = getattr(settings, "PRODUCT_NAME", "Tadgeeg AI")
    company_name = getattr(settings, "COMPANY_NAME", "Get Solution Company")
    company_name_ar = getattr(settings, "COMPANY_NAME_AR", "شركة Get Solution")
    product_tagline_ar = getattr(
        settings,
        "PRODUCT_TAGLINE_AR",
        "منصة الذكاء الاصطناعي للتدقيق المالي والامتثال",
    )
    product_tagline_en = getattr(
        settings,
        "PRODUCT_TAGLINE_EN",
        "AI platform for financial auditing and compliance",
    )
    product_description_ar = getattr(
        settings,
        "PRODUCT_DESCRIPTION_AR",
        "منصة الذكاء الاصطناعي الرائدة للتدقيق المالي والامتثال",
    )
    product_description_en = getattr(
        settings,
        "PRODUCT_DESCRIPTION_EN",
        "Leading AI platform for financial auditing and compliance",
    )

    company_display_name = company_name_ar if is_arabic else company_name
    product_tagline = product_tagline_ar if is_arabic else product_tagline_en
    product_description = product_description_ar if is_arabic else product_description_en
    company_byline = f"من تطوير {company_name_ar}" if is_arabic else f"By {company_name}"
    company_product_label = (
        f"أحد منتجات {company_name_ar}"
        if is_arabic
        else f"A product by {company_name}"
    )

    return {
        "product_name": product_name,
        "company_name": company_name,
        "company_name_ar": company_name_ar,
        "company_display_name": company_display_name,
        "product_tagline": product_tagline,
        "product_tagline_ar": product_tagline_ar,
        "product_tagline_en": product_tagline_en,
        "product_description": product_description,
        "product_description_ar": product_description_ar,
        "product_description_en": product_description_en,
        "company_byline": company_byline,
        "company_product_label": company_product_label,
        "product_signature": f"{product_name} {company_byline}",
        "product_signature_en": f"{product_name} by {company_name}",
        "product_signature_ar": f"{product_name} من تطوير {company_name_ar}",
    }
