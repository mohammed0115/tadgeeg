"""A partner card on an Arabic page must read in Arabic — and leak nothing.

The public /partners/ page rendered «Bironex Holding» in Latin script inside an
otherwise Arabic card, because Partner carried one name field. That is the same
failure this project guards against everywhere else, arriving through the data
layer instead of a template.

The second half of this file is the more important half: a partner record holds
a contact email and phone that were given for the relationship, not for
publication. Partner.PUBLIC_FIELDS is the boundary, and a test that only checks
the tuple would pass while a template printed the field anyway — so the
rendered page is checked too.
"""

from pathlib import Path

import pytest
from django.test import Client
from django.utils import translation

from apps.partners.models import Partner, PartnerStatus, PartnerTier, PartnerType

BASE_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def bironex(db):
    partner = Partner.objects.create(
        slug="bironex-holding",
        company_name="Bironex Holding",
        company_name_ar="شركة بيرونيكس القابضة",
        country="SA",
        website="https://bironex.sa",
        contact_email="info@bironex.sa",
        contact_phone="056929862",
        short_description="شريك استراتيجي في تطوير الحلول الرقمية.",
        partner_type=PartnerType.STRATEGIC,
        partner_tier=PartnerTier.STRATEGIC,
        status=PartnerStatus.PUBLISHED,
    )
    return partner


# ── Language ──────────────────────────────────────────────────────────────────

def test_arabic_pages_use_the_arabic_name(bironex):
    with translation.override("ar"):
        assert bironex.display_name == "شركة بيرونيكس القابضة"


def test_english_pages_use_the_latin_name(bironex):
    with translation.override("en"):
        assert bironex.display_name == "Bironex Holding"


@pytest.mark.django_db
def test_a_partner_with_no_arabic_name_reads_in_latin_rather_than_blank():
    """Falling back beats rendering an empty card."""
    partner = Partner.objects.create(
        slug="latin-only", company_name="Acme Systems", status=PartnerStatus.PUBLISHED
    )
    with translation.override("ar"):
        assert partner.display_name == "Acme Systems"


@pytest.mark.django_db
def test_the_public_page_renders_the_arabic_name(bironex):
    response = Client().get("/partners/", HTTP_ACCEPT_LANGUAGE="ar")
    assert response.status_code == 200
    assert "شركة بيرونيكس القابضة" in response.content.decode()


# ── Disclosure ────────────────────────────────────────────────────────────────

def test_contact_details_are_not_public_fields():
    assert "contact_email" not in Partner.PUBLIC_FIELDS
    assert "contact_phone" not in Partner.PUBLIC_FIELDS


@pytest.mark.django_db
def test_the_public_page_does_not_print_the_partners_contact_details(bironex):
    """The boundary that matters is the rendered byte stream, not the tuple."""
    body = Client().get("/partners/", HTTP_ACCEPT_LANGUAGE="ar").content.decode()
    assert "info@bironex.sa" not in body
    assert "056929862" not in body


@pytest.mark.django_db
def test_the_website_is_public_and_opens_safely(bironex):
    body = Client().get("/partners/", HTTP_ACCEPT_LANGUAGE="ar").content.decode()
    assert "https://bironex.sa" in body
    assert 'rel="noopener noreferrer"' in body, \
        "target=_blank without noopener hands the opener window to the partner site"


@pytest.mark.django_db
def test_an_unpublished_partner_is_invisible_regardless_of_language(bironex):
    bironex.status = PartnerStatus.DRAFT
    bironex.save(update_fields=["status"])
    body = Client().get("/partners/", HTTP_ACCEPT_LANGUAGE="ar").content.decode()
    assert "بيرونيكس" not in body
    assert "Bironex" not in body


# ── The seeding path ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_seeding_is_idempotent_and_does_not_republish_a_hidden_partner():
    """A redeploy must not undo an operator's decision to hide a partner."""
    from django.core.management import call_command

    call_command("seed_partners", verbosity=0)
    partner = Partner.objects.get(slug="bironex-holding")
    partner.status = PartnerStatus.HIDDEN
    partner.save(update_fields=["status"])

    call_command("seed_partners", verbosity=0)

    partner.refresh_from_db()
    assert partner.status == PartnerStatus.HIDDEN
    assert Partner.objects.filter(slug="bironex-holding").count() == 1


@pytest.mark.django_db
def test_seeding_fills_the_identity_the_public_page_needs():
    from django.core.management import call_command

    call_command("seed_partners", verbosity=0)
    partner = Partner.objects.get(slug="bironex-holding")
    assert partner.company_name_ar == "شركة بيرونيكس القابضة"
    assert partner.website == "https://bironex.sa"


def test_the_logo_directory_is_documented_rather_than_silently_empty():
    """An empty directory teaches nobody where to put the file."""
    readme = BASE_DIR / "apps/partners/seed_assets/README.md"
    assert readme.exists()
    assert "bironex-holding.png" in readme.read_text(encoding="utf-8")


# ── Descriptions, and the mirror-image bug ───────────────────────────────────
# The name fix left the other half: an English visitor read an Arabic paragraph
# under a Latin company name. Partner copy is DATA, so it cannot go through the
# gettext catalogue — the translation has to live on the row, which means the
# model needs the second column and every surface needs the resolved property.

@pytest.fixture
def bilingual(db):
    return Partner.objects.create(
        slug="bironex-holding",
        company_name="Bironex Holding",
        company_name_ar="شركة بيرونيكس القابضة",
        short_description="شريك استراتيجي في تطوير الحلول الرقمية.",
        short_description_en="A strategic partner in digital solutions.",
        long_description="نصّ عربي مطوّل.",
        long_description_en="A longer English body.",
        country="SA", website="https://bironex.sa",
        partner_type=PartnerType.STRATEGIC, partner_tier=PartnerTier.STRATEGIC,
        status=PartnerStatus.PUBLISHED,
    )


def test_the_description_follows_the_active_language(bilingual):
    with translation.override("ar"):
        assert bilingual.display_short_description.startswith("شريك")
    with translation.override("en"):
        assert bilingual.display_short_description.startswith("A strategic")


@pytest.mark.django_db
def test_a_missing_english_description_falls_back_to_arabic():
    """Arabic under an English heading beats an empty card."""
    partner = Partner.objects.create(
        slug="ar-only", company_name="Acme",
        short_description="وصف عربي فقط", status=PartnerStatus.PUBLISHED,
    )
    with translation.override("en"):
        assert partner.display_short_description == "وصف عربي فقط"


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/partners/", "/partners/bironex-holding/"])
def test_no_arabic_copy_leaks_onto_the_english_pages(bilingual, path):
    client = Client()
    client.cookies["django_language"] = "en"
    body = client.get(path).content.decode()

    assert "A strategic partner in digital solutions" in body
    assert "شريك استراتيجي في تطوير" not in body
    assert "شركة بيرونيكس القابضة" not in body


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/partners/", "/partners/bironex-holding/"])
def test_no_latin_copy_leaks_onto_the_arabic_pages(bilingual, path):
    client = Client()
    client.cookies["django_language"] = "ar"
    body = client.get(path).content.decode()

    assert "شركة بيرونيكس القابضة" in body
    assert "Bironex Holding" not in body


@pytest.mark.django_db
def test_the_page_title_and_meta_description_follow_the_language(bilingual):
    """These are what a search engine indexes and a shared link previews.

    They were reading the raw columns, which put a Latin name in the Arabic
    page's title bar — invisible in the page body, visible in every search
    result and every WhatsApp link preview.
    """
    client = Client()
    client.cookies["django_language"] = "ar"
    body = client.get("/partners/bironex-holding/").content.decode()

    title = body.split("<title>")[1].split("</title>")[0]
    assert "شركة بيرونيكس القابضة" in title
    assert "Bironex" not in title


def test_the_public_payload_carries_the_resolved_fields(bilingual):
    """The detail page renders from this dict, not from the model."""
    with translation.override("en"):
        payload = bilingual.public_payload()
    assert payload["display_name"] == "Bironex Holding"
    assert payload["display_short_description"].startswith("A strategic")
    # The raw columns stay available for an API consumer that wants both.
    assert payload["short_description"].startswith("شريك")


def test_contact_details_are_still_absent_after_adding_public_fields(bilingual):
    """PUBLIC_FIELDS grew by four entries; the boundary must not have moved."""
    payload = bilingual.public_payload()
    assert "contact_email" not in payload
    assert "contact_phone" not in payload
