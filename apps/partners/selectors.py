"""Read paths for the partner ecosystem.

Everything public goes through ``Partner.published``, so an unpublished record
is unreachable from a public surface by construction rather than by remembering
to filter (§D4).
"""

from __future__ import annotations

from .models import Partner, PartnerStatus, PartnerTier, PartnerType


#: Public page section order (§D3 / §L.2). The page groups by TIER, plus one
#: section keyed on TYPE:
#:
#:   * strategic  → hero, doubled visual area   (tier)
#:   * platinum / gold / silver                  (tier)
#:   * distributors                              (TYPE — deliberately not a tier)
#:
#: A distributor holding a tier appears in BOTH their tier section and the
#: distributors section. That is intended, not duplication to be removed: the
#: two sections answer different questions.
TIER_SECTIONS = (
    (PartnerTier.PLATINUM, "PLATINUM"),
    (PartnerTier.GOLD, "GOLD"),
    (PartnerTier.SILVER, "SILVER"),
)


def get_public_partners():
    """Every published partner, ordered for display."""
    return Partner.published.all().order_by("display_order", "company_name")


def get_strategic_partners():
    """Hero partners — selected by TIER, per §D3."""
    return get_public_partners().filter(partner_tier=PartnerTier.STRATEGIC)


def get_public_sections():
    """Sections for /partners/, in approved display order.

    Returns a list of dicts so the template does no filtering of its own — the
    publish gate and the grouping both live here.
    """
    sections = []

    for tier_value, badge in TIER_SECTIONS:
        partners = list(get_public_partners().filter(partner_tier=tier_value))
        if partners:
            sections.append({
                "key": tier_value,
                "badge": badge,
                "partners": partners,
            })

    distributors = list(
        get_public_partners().filter(partner_type=PartnerType.DISTRIBUTOR)
    )
    if distributors:
        sections.append({
            "key": "distributors",
            "badge": "DISTRIBUTOR",
            "partners": distributors,
        })

    return sections


def get_public_partner_by_slug(slug: str):
    """A published partner, or None.

    None (→ 404) rather than a permission error for an unpublished slug: a 403
    would confirm the record exists, which tells an anonymous visitor about
    partners the company has not announced.
    """
    return Partner.published.filter(slug=slug).first()


# ── admin ────────────────────────────────────────────────────────────────────

def list_partners_for_admin(*, q=None, country=None, partner_type=None,
                            partner_tier=None, status=None):
    """Unfiltered by publication state — staff manage drafts too.

    Every filter value is validated against a known set; an unrecognised value
    is ignored rather than handed to the ORM.
    """
    queryset = Partner.objects.all()

    if q:
        from django.db.models import Q

        queryset = queryset.filter(
            Q(company_name__icontains=q)
            | Q(slug__icontains=q)
            | Q(short_description__icontains=q)
        )
    if country:
        queryset = queryset.filter(country=country)
    if partner_type and partner_type in PartnerType.values:
        queryset = queryset.filter(partner_type=partner_type)
    if partner_tier and partner_tier in PartnerTier.values:
        queryset = queryset.filter(partner_tier=partner_tier)
    if status and status in PartnerStatus.values:
        queryset = queryset.filter(status=status)

    return queryset.order_by("display_order", "company_name")


def admin_row(partner: Partner) -> dict:
    """Staff-facing representation.

    Includes the contact fields — staff are the audience §C.4 controls them
    for. This must never be reused for a public response; that is what
    ``Partner.public_payload()`` is for.
    """
    return {
        "id": str(partner.id),
        "company_name": partner.company_name,
        "slug": partner.slug,
        "country": str(partner.country or ""),
        "short_description": partner.short_description,
        "website": partner.website,
        "partner_type": partner.partner_type,
        "partner_tier": partner.partner_tier,
        "status": partner.status,
        "display_order": partner.display_order,
        "contact_email": partner.contact_email,
        "contact_phone": partner.contact_phone,
        "logo_url": partner.logo.url if partner.logo else "",
        "published_at": partner.published_at.isoformat() if partner.published_at else "",
        "created_at": partner.created_at.isoformat() if partner.created_at else "",
    }


# ── applications (Phase 2B) ──────────────────────────────────────────────────

def list_applications_for_admin(*, q=None, country=None,
                                requested_partner_type=None, status=None):
    """Staff-only application queryset. There is no public counterpart.

    Filter values are validated against known sets; an unrecognised value is
    ignored rather than handed to the ORM. Exports call this with the same
    arguments as the list view, which is what makes "the export respects the
    filters" true by construction rather than by keeping two paths in step.
    """
    from django.db.models import Q

    from .models import ApplicationStatus, PartnerApplication

    queryset = PartnerApplication.objects.all().prefetch_related("attachments")

    if q:
        queryset = queryset.filter(
            Q(company_name__icontains=q)
            | Q(contact_name__icontains=q)
            | Q(email__icontains=q)
        )
    if country:
        queryset = queryset.filter(country=country)
    if requested_partner_type and requested_partner_type in PartnerType.values:
        queryset = queryset.filter(requested_partner_type=requested_partner_type)
    if status and status in ApplicationStatus.values:
        queryset = queryset.filter(status=status)

    return queryset.order_by("-created_at")


def application_row(application) -> dict:
    """Staff-facing list row.

    ``submitted_ip`` is intentionally absent: it exists for abuse triage and is
    visible on the detail view and in Django admin, not scattered through list
    payloads and exports. Internal notes are absent for the same reason.
    """
    return {
        "id": str(application.id),
        "company_name": application.company_name,
        "contact_name": application.contact_name,
        "email": application.email,
        "mobile": application.mobile,
        "country": str(application.country or ""),
        "city": application.city,
        "website": application.website,
        "requested_partner_type": application.requested_partner_type,
        "business_areas": application.business_areas or [],
        "status": application.status,
        "attachment_count": application.attachments.count(),
        "created_at": application.created_at.isoformat() if application.created_at else "",
        "reviewed_at": application.reviewed_at.isoformat() if application.reviewed_at else "",
    }
