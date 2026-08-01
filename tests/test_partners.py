"""Partner ecosystem — public exposure, grouping, administration (Phase 2A).

Two things carry most of the weight here.

**The publish gate is asserted at the queryset level**, not only against
rendered HTML. A template assertion passes just as happily when the filter has
moved into the template — which is exactly the refactor that leaks drafts.

**The public allow-list is asserted by absence.** ``contact_email`` and
``contact_phone`` are stored but must never be served (§C.4/§N), so the tests
check they appear in no public response at all, not merely that the template
does not print them today.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.authentication.models import AuditLog, Organization
from apps.partners.models import Partner, PartnerStatus, PartnerTier, PartnerType
from apps.partners.selectors import (
    get_public_partner_by_slug,
    get_public_partners,
    get_public_sections,
    get_strategic_partners,
)

pytestmark = pytest.mark.django_db

User = get_user_model()

ADMIN_LIST = "/api/platform-admin/partners/"


def make_partner(slug, *, status=PartnerStatus.PUBLISHED, tier=PartnerTier.SILVER,
                 ptype=PartnerType.DISTRIBUTOR, name=None, **extra):
    return Partner.objects.create(
        slug=slug,
        company_name=name or slug.replace("-", " ").title(),
        status=status,
        partner_tier=tier,
        partner_type=ptype,
        short_description=f"About {slug}",
        country="SA",
        **extra,
    )


@pytest.fixture
def staff_user(db):
    user = User.objects.create_user(
        email="staff@tadgeeg.test", password="StrongPass123!", full_name="Staff",
    )
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return user


@pytest.fixture
def org_admin_user(db):
    """A customer: role=ADMIN, is_staff=False — what every registrant gets.

    Given a usable subscription so SubscriptionRequiredMiddleware does not
    answer 402 before the permission class is reached; otherwise the assertions
    would pass for the wrong reason.
    """
    from io import StringIO

    from django.core.management import call_command

    from apps.billing.services.subscription_service import SubscriptionService

    call_command("seed_billing_plans", stdout=StringIO())
    org = Organization.objects.create(name="Customer Co")
    user = User.objects.create_user(
        email="customer@example.com", password="StrongPass123!",
        full_name="Customer", role=User.Role.ADMIN, organization=org,
    )
    SubscriptionService().create_free_trial(org)
    return user


# ── D4: only Published is ever public, enforced at the data layer ────────────

@pytest.mark.parametrize(
    "status", [PartnerStatus.DRAFT, PartnerStatus.HIDDEN, PartnerStatus.SUSPENDED]
)
def test_unpublished_partners_are_invisible_at_the_queryset_level(status):
    make_partner("hidden-co", status=status)
    assert get_public_partners().count() == 0
    assert Partner.published.count() == 0
    # ...while the record itself still exists for staff.
    assert Partner.objects.count() == 1


def test_published_partner_is_visible():
    make_partner("visible-co")
    assert get_public_partners().count() == 1


def test_public_page_lists_only_published(client):
    make_partner("shown-co", name="Shown Co")
    make_partner("draft-co", name="Draft Co", status=PartnerStatus.DRAFT)

    body = client.get(reverse("frontend:partners")).content.decode()
    assert "Shown Co" in body
    assert "Draft Co" not in body


def test_detail_page_404s_for_unpublished(client):
    make_partner("secret-co", status=PartnerStatus.DRAFT)
    resp = client.get(reverse("frontend:partner_detail", args=["secret-co"]))
    assert resp.status_code == 404, (
        "an unpublished partner must 404, not 403 — a 403 confirms the record exists"
    )


def test_detail_page_renders_for_published(client):
    make_partner("open-co", name="Open Co")
    resp = client.get(reverse("frontend:partner_detail", args=["open-co"]))
    assert resp.status_code == 200
    assert "Open Co" in resp.content.decode()


def test_selector_returns_none_for_unpublished():
    make_partner("nope-co", status=PartnerStatus.SUSPENDED)
    assert get_public_partner_by_slug("nope-co") is None


# ── allow-list: contact details are stored but never served ──────────────────

def test_contact_details_never_appear_on_public_surfaces(client):
    make_partner(
        "contactable-co",
        contact_email="secret@partner.example",
        contact_phone="+966500000000",
    )

    listing = client.get(reverse("frontend:partners")).content.decode()
    detail = client.get(reverse("frontend:partner_detail", args=["contactable-co"])).content.decode()

    for body in (listing, detail):
        assert "secret@partner.example" not in body
        assert "+966500000000" not in body


def test_public_payload_excludes_contact_fields():
    partner = make_partner(
        "payload-co", contact_email="a@b.example", contact_phone="+966500000000",
    )
    payload = partner.public_payload()
    assert "contact_email" not in payload
    assert "contact_phone" not in payload
    assert payload["company_name"] == partner.company_name


def test_public_fields_allowlist_is_exhaustive():
    """A field added to the model later must be private by default."""
    assert "contact_email" not in Partner.PUBLIC_FIELDS
    assert "contact_phone" not in Partner.PUBLIC_FIELDS
    assert "source_application" not in Partner.PUBLIC_FIELDS
    assert "status" not in Partner.PUBLIC_FIELDS


# ── D3: grouping is by tier, plus one section keyed on type ──────────────────

def test_strategic_hero_is_selected_by_tier_not_type():
    make_partner("strat-co", tier=PartnerTier.STRATEGIC, ptype=PartnerType.STRATEGIC)
    # Type=strategic but tier=gold must NOT be in the hero.
    make_partner("gold-co", tier=PartnerTier.GOLD, ptype=PartnerType.STRATEGIC)

    heroes = [p.slug for p in get_strategic_partners()]
    assert heroes == ["strat-co"]


def test_distributor_with_a_tier_appears_in_both_sections():
    """Intended, not duplication: the sections answer different questions."""
    make_partner("dual-co", tier=PartnerTier.SILVER, ptype=PartnerType.DISTRIBUTOR)

    sections = {s["key"]: [p.slug for p in s["partners"]] for s in get_public_sections()}
    assert "dual-co" in sections["silver"]
    assert "dual-co" in sections["distributors"]


def test_technical_partner_without_a_tier_appears_in_no_section():
    """A documented consequence of the approved design, not a bug (§D3)."""
    make_partner("tech-co", tier="", ptype=PartnerType.TECHNICAL)

    sections = get_public_sections()
    all_slugs = [p.slug for s in sections for p in s["partners"]]
    assert "tech-co" not in all_slugs
    assert get_public_partners().count() == 1, "the record is published, just unsectioned"


def test_training_partner_without_a_tier_appears_in_no_section():
    make_partner("train-co", tier="", ptype=PartnerType.TRAINING)
    all_slugs = [p.slug for s in get_public_sections() for p in s["partners"]]
    assert "train-co" not in all_slugs


def test_sections_are_in_approved_order():
    make_partner("p-co", tier=PartnerTier.PLATINUM, ptype=PartnerType.TECHNICAL)
    make_partner("g-co", tier=PartnerTier.GOLD, ptype=PartnerType.TECHNICAL)
    make_partner("s-co", tier=PartnerTier.SILVER, ptype=PartnerType.TECHNICAL)
    make_partner("d-co", tier="", ptype=PartnerType.DISTRIBUTOR)

    assert [s["key"] for s in get_public_sections()] == [
        "platinum", "gold", "silver", "distributors",
    ]


def test_empty_sections_are_omitted():
    make_partner("only-gold", tier=PartnerTier.GOLD, ptype=PartnerType.TECHNICAL)
    assert [s["key"] for s in get_public_sections()] == ["gold"]


# ── type / tier / status are independent ─────────────────────────────────────

def test_type_tier_and_status_are_separate_fields():
    partner = make_partner(
        "sep-co", tier=PartnerTier.GOLD, ptype=PartnerType.TRAINING,
        status=PartnerStatus.DRAFT,
    )
    assert partner.partner_type == "training"
    assert partner.partner_tier == "gold"
    assert partner.status == "draft"
    # Three distinct model fields, not one.
    names = {f.name for f in Partner._meta.get_fields()}
    assert {"partner_type", "partner_tier", "status"} <= names


def test_strategic_exists_in_both_type_and_tier():
    """Deliberate overlap (§D2) — asserted so nobody 'fixes' it."""
    assert "strategic" in PartnerType.values
    assert "strategic" in PartnerTier.values


# ── slug behaviour ───────────────────────────────────────────────────────────

def test_slug_is_unique():
    from django.db import IntegrityError

    make_partner("dupe-co")
    with pytest.raises(IntegrityError):
        make_partner("dupe-co", name="Another")


def test_slug_is_derived_and_deduplicated_on_create(client, staff_user):
    client.force_login(staff_user)
    first = client.post(ADMIN_LIST, data={"company_name": "Acme Partners"},
                        content_type="application/json")
    second = client.post(ADMIN_LIST, data={"company_name": "Acme Partners"},
                         content_type="application/json")
    assert first.status_code == 201, first.content[:300]
    assert second.status_code == 201, second.content[:300]
    assert first.json()["slug"] == "acme-partners"
    assert second.json()["slug"] == "acme-partners-2"


def test_explicit_duplicate_slug_is_rejected(client, staff_user):
    make_partner("taken-co")
    client.force_login(staff_user)
    resp = client.post(
        ADMIN_LIST,
        data={"company_name": "Other", "slug": "taken-co"},
        content_type="application/json",
    )
    assert resp.status_code == 400


# ── admin permissions: every endpoint, all three identities ──────────────────

def _admin_endpoints(partner):
    return [
        ("get", ADMIN_LIST, None),
        ("get", f"{ADMIN_LIST}{partner.id}/", None),
        ("post", f"{ADMIN_LIST}{partner.id}/publish/", {}),
        ("post", f"{ADMIN_LIST}{partner.id}/hide/", {}),
        ("post", f"{ADMIN_LIST}reorder/", {"order": [{"id": str(partner.id), "display_order": 1}]}),
    ]


def test_anonymous_cannot_reach_partner_admin(client):
    partner = make_partner("anon-co")
    for method, url, payload in _admin_endpoints(partner):
        call = getattr(client, method)
        resp = call(url, data=payload, content_type="application/json") if payload is not None else call(url)
        assert resp.status_code in (401, 403), f"{method.upper()} {url} → {resp.status_code}"


def test_org_admin_role_cannot_reach_partner_admin(client, org_admin_user):
    partner = make_partner("role-co")
    client.force_login(org_admin_user)
    for method, url, payload in _admin_endpoints(partner):
        call = getattr(client, method)
        resp = call(url, data=payload, content_type="application/json") if payload is not None else call(url)
        assert resp.status_code == 403, (
            f"{method.upper()} {url} → {resp.status_code} for a non-staff user "
            "whose role is 'admin'. Every registrant has that role."
        )


def test_staff_can_list_partners(client, staff_user):
    make_partner("listed-co", name="Listed Co")
    client.force_login(staff_user)
    resp = client.get(ADMIN_LIST)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["company_name"] == "Listed Co"


def test_staff_list_includes_unpublished(client, staff_user):
    make_partner("draft-co", status=PartnerStatus.DRAFT)
    client.force_login(staff_user)
    assert client.get(ADMIN_LIST).json()["count"] == 1


def test_admin_filters(client, staff_user):
    make_partner("sa-gold", tier=PartnerTier.GOLD)
    make_partner("sa-silver", tier=PartnerTier.SILVER)
    client.force_login(staff_user)

    assert client.get(ADMIN_LIST + "?partner_tier=gold").json()["count"] == 1
    assert client.get(ADMIN_LIST + "?q=sa-silver").json()["count"] == 1
    assert client.get(ADMIN_LIST + "?status=published").json()["count"] == 2
    # An unrecognised filter value is ignored, not passed to the ORM.
    assert client.get(ADMIN_LIST + "?partner_tier=bogus").json()["count"] == 2


def test_status_cannot_be_changed_by_patch(client, staff_user):
    """Visibility changes must go through the audited endpoints."""
    partner = make_partner("patch-co", status=PartnerStatus.DRAFT)
    client.force_login(staff_user)
    resp = client.patch(
        f"{ADMIN_LIST}{partner.id}/",
        data={"status": "published"}, content_type="application/json",
    )
    assert resp.status_code == 200
    partner.refresh_from_db()
    assert partner.status == PartnerStatus.DRAFT, "status is read-only on the serializer"


# ── publish / hide are audited ───────────────────────────────────────────────

def test_publish_makes_public_and_is_audited(client, staff_user):
    partner = make_partner("pub-co", status=PartnerStatus.DRAFT)
    client.force_login(staff_user)

    resp = client.post(f"{ADMIN_LIST}{partner.id}/publish/", data={},
                       content_type="application/json")
    assert resp.status_code == 200

    partner.refresh_from_db()
    assert partner.status == PartnerStatus.PUBLISHED
    assert partner.published_at is not None
    assert get_public_partners().count() == 1

    entry = AuditLog.objects.filter(details__action_type="partner_published").first()
    assert entry is not None, "publishing must be audited"
    assert entry.user_id == staff_user.id
    assert entry.details["old_value"]["status"] == "draft"
    assert entry.details["new_value"]["status"] == "published"


def test_hide_removes_from_public_and_is_audited(client, staff_user):
    partner = make_partner("hide-co")
    partner.publish()
    first_published = partner.published_at
    client.force_login(staff_user)

    resp = client.post(f"{ADMIN_LIST}{partner.id}/hide/", data={},
                       content_type="application/json")
    assert resp.status_code == 200

    partner.refresh_from_db()
    assert partner.status == PartnerStatus.HIDDEN
    assert get_public_partners().count() == 0
    assert partner.published_at == first_published, (
        "hiding must preserve the first-published date"
    )

    entry = AuditLog.objects.filter(details__action_type="partner_hidden").first()
    assert entry is not None
    assert entry.details["new_value"]["status"] == "hidden"


def test_republishing_does_not_move_published_at(client, staff_user):
    partner = make_partner("re-co", status=PartnerStatus.DRAFT)
    client.force_login(staff_user)

    client.post(f"{ADMIN_LIST}{partner.id}/publish/", data={}, content_type="application/json")
    partner.refresh_from_db()
    original = partner.published_at

    client.post(f"{ADMIN_LIST}{partner.id}/hide/", data={}, content_type="application/json")
    client.post(f"{ADMIN_LIST}{partner.id}/publish/", data={}, content_type="application/json")
    partner.refresh_from_db()
    assert partner.published_at == original


def test_publish_unknown_partner_returns_404(client, staff_user):
    client.force_login(staff_user)
    resp = client.post(
        f"{ADMIN_LIST}0f9b7c62-1d2e-4a3b-8c5d-6e7f8a9b0c1d/publish/",
        data={}, content_type="application/json",
    )
    assert resp.status_code == 404


# ── reorder ──────────────────────────────────────────────────────────────────

def test_reorder_sets_display_order(client, staff_user):
    a = make_partner("a-co")
    b = make_partner("b-co")
    client.force_login(staff_user)

    resp = client.post(
        f"{ADMIN_LIST}reorder/",
        data={"order": [{"id": str(a.id), "display_order": 5},
                        {"id": str(b.id), "display_order": 1}]},
        content_type="application/json",
    )
    assert resp.status_code == 200
    a.refresh_from_db(); b.refresh_from_db()
    assert (a.display_order, b.display_order) == (5, 1)
    # Ordering is reflected publicly.
    assert [p.slug for p in get_public_partners()] == ["b-co", "a-co"]


def test_reorder_rejects_a_bad_payload(client, staff_user):
    client.force_login(staff_user)
    for payload in ({"order": []}, {"order": "nope"}, {}):
        resp = client.post(f"{ADMIN_LIST}reorder/", data=payload,
                           content_type="application/json")
        assert resp.status_code == 400


# ── seed ─────────────────────────────────────────────────────────────────────

def test_seed_creates_bironex_as_data():
    from io import StringIO

    from django.core.management import call_command

    call_command("seed_partners", stdout=StringIO())
    partner = Partner.objects.get(slug="bironex-holding")

    assert partner.company_name == "Bironex Holding"
    assert partner.partner_tier == PartnerTier.STRATEGIC
    assert partner.status == PartnerStatus.PUBLISHED
    assert partner.published_at is not None
    assert "الذكاء الاصطناعي" in partner.short_description
    # It reaches the hero, i.e. it is real data driving the page.
    assert [p.slug for p in get_strategic_partners()] == ["bironex-holding"]


def test_seed_is_idempotent_and_respects_a_manual_hide():
    from io import StringIO

    from django.core.management import call_command

    call_command("seed_partners", stdout=StringIO())
    Partner.objects.filter(slug="bironex-holding").first().hide()

    call_command("seed_partners", stdout=StringIO())
    assert Partner.objects.filter(slug="bironex-holding").count() == 1
    assert Partner.objects.get(slug="bironex-holding").status == PartnerStatus.HIDDEN, (
        "a redeploy must not silently republish a partner an operator hid"
    )


def test_bironex_is_not_hardcoded_in_the_template(client):
    """The page must be empty without seed data — proof it is data-driven."""
    body = client.get(reverse("frontend:partners")).content.decode()
    assert "Bironex" not in body


# ── the join CTA must not lead nowhere silently ──────────────────────────────

def test_join_cta_links_to_the_application_form(client):
    """Phase 2B opened the form, so the CTA is now a live link.

    This test previously asserted the button was DISABLED with an explanatory
    note — correct for 2A, when the form did not exist. Both the disabled state
    and the note were removed together in 2B; leaving either would contradict
    the other.
    """
    body = client.get(reverse("frontend:partners")).content.decode()
    assert "Join as a Partner" in body or "انضم" in body
    assert "/partners/apply/" in body
    assert "not open yet" not in body, "the 'not open yet' note must go with the disabled state"


# ── console shell ────────────────────────────────────────────────────────────

def test_partner_console_requires_staff(client, org_admin_user):
    client.force_login(org_admin_user)
    assert client.get("/platform-admin/partners/").status_code in (302, 403)


def test_partner_console_renders_for_staff(client, staff_user):
    client.force_login(staff_user)
    resp = client.get("/platform-admin/partners/")
    assert resp.status_code == 200
    assert "partnersAdmin()" in resp.content.decode()


# ── template hygiene ─────────────────────────────────────────────────────────

def test_no_multiline_django_comments_leak_into_rendered_pages():
    """`{# ... #}` is SINGLE-LINE only — a multi-line one renders as page text.

    This shipped in Phase 1: four multi-line `{# #}` comments in
    templates/auth/portal.html were being printed to visitors on the live
    registration form, and no test caught it because the registration tests
    assert that fields are PRESENT, never that developer notes are absent.
    Found only by screenshotting the running app.

    Use {% comment %}...{% endcomment %} for anything spanning lines.
    """
    import re
    from pathlib import Path

    from django.conf import settings

    offenders = []
    for path in (Path(settings.BASE_DIR) / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\{#(.*?)#\}", text, re.S):
            if "\n" in match.group(1):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(settings.BASE_DIR)}:{line}")

    assert not offenders, (
        "Multi-line {# #} comments render as visible page text. Convert them to "
        "{% comment %} blocks:\n" + "\n".join(offenders)
    )


def test_partners_page_does_not_render_developer_notes(client):
    body = client.get(reverse("frontend:partners")).content.decode()
    assert "{#" not in body and "#}" not in body
    assert "Phase 2B" not in body, "internal phase language must not reach visitors"
