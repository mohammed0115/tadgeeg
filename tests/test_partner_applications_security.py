"""Phase 2B security suite — the upload surface is the control being tested.

``/api/v1/partners/applications/`` is the product's only unauthenticated write
path that accepts files, from strangers, carrying commercial registration
documents. The tests below are the security control, not a demonstration of it.

Three properties get the most attention:

* **Nothing hostile reaches storage.** Every rejection case also asserts that no
  attachment row and no file exist afterwards — a rejected upload that still
  wrote bytes is still a foothold.
* **Content is checked, not the extension.** The `.exe`-renamed-to-`.pdf` case
  is the headline: an extension is a claim.
* **Documents are unreachable without staff authority.** Asserted by attempting
  retrieval, not by reading the config.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.authentication.models import AuditLog, Organization
from apps.partners.models import (
    ApplicationStatus,
    Partner,
    PartnerApplication,
    PartnerApplicationAttachment,
    PartnerStatus,
    PartnerTier,
)

pytestmark = pytest.mark.django_db

User = get_user_model()

SUBMIT_URL = "/api/v1/partners/applications/"

# Real magic bytes, so a "valid" fixture is genuinely valid.
PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def valid_payload(**overrides):
    payload = {
        "company_name": "Bironex Partners",
        "contact_name": "Sara Ahmed",
        "position": "BD Manager",
        "email": "apply@example.com",
        "mobile": "+966501234567",
        "country": "SA",
        "city": "Riyadh",
        "requested_partner_type": "distributor",
        "business_areas": ["erp", "ai"],
        "company_summary": "We integrate ERP systems.",
        "declaration_accepted": "true",
    }
    payload.update(overrides)
    return payload


def upload(name, content):
    return SimpleUploadedFile(name, content)


def stored_file_count():
    root = Path(settings.PARTNER_DOCS_ROOT)
    if not root.exists():
        return 0
    return len([p for p in root.iterdir() if p.is_file()])


@pytest.fixture(autouse=True)
def isolated_private_storage(tmp_path, settings):
    """Point private storage at a temp dir so tests never touch real documents.

    autouse: every test in this module writes or asserts about storage, and one
    test forgetting the fixture would write a hostile fixture file into the
    developer's real private_media directory.
    """
    root = tmp_path / "partner_docs"
    root.mkdir(parents=True, exist_ok=True)
    settings.PARTNER_DOCS_ROOT = root

    # DRF throttling counts per IP in the cache, and the test client always
    # presents the same IP. Without clearing, the 6th test in this module would
    # start receiving 429 and every later assertion would be testing the
    # throttle instead of the thing it names.
    from django.core.cache import cache

    cache.clear()
    yield root
    cache.clear()


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


# ═══ upload rejection matrix ═════════════════════════════════════════════════
# Each case asserts BOTH a 400 and that nothing was persisted. A rejection that
# still wrote the file to disk is not a rejection.

def _assert_nothing_persisted():
    assert PartnerApplication.objects.count() == 0, "a rejected submission created an application"
    assert PartnerApplicationAttachment.objects.count() == 0, "a rejected upload created an attachment"
    assert stored_file_count() == 0, "a rejected upload wrote bytes to storage"


def test_executable_renamed_to_pdf_is_rejected(client):
    """THE headline case: the extension is a claim, the bytes are the evidence."""
    evil = upload("invoice.pdf", b"MZ\x90\x00\x03" + b"\x00" * 100)  # PE header
    resp = client.post(SUBMIT_URL, data=valid_payload(commercial_register=evil))
    assert resp.status_code == 400, resp.content[:300]
    _assert_nothing_persisted()


def test_html_disguised_as_pdf_is_rejected(client):
    evil = upload("profile.pdf", b"<html><body><script>alert(1)</script></body></html>")
    assert client.post(SUBMIT_URL, data=valid_payload(company_profile=evil)).status_code == 400
    _assert_nothing_persisted()


def test_svg_is_rejected(client):
    svg = upload("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
    assert client.post(SUBMIT_URL, data=valid_payload(logo=svg)).status_code == 400
    _assert_nothing_persisted()


def test_html_file_is_rejected(client):
    assert client.post(
        SUBMIT_URL, data=valid_payload(other_files=upload("x.html", b"<html></html>"))
    ).status_code == 400
    _assert_nothing_persisted()


def test_archive_is_rejected(client):
    zip_bytes = b"PK\x03\x04" + b"\x00" * 100
    assert client.post(
        SUBMIT_URL, data=valid_payload(other_files=upload("docs.zip", zip_bytes))
    ).status_code == 400
    _assert_nothing_persisted()


def test_oversize_single_file_is_rejected(client, settings):
    settings.PARTNER_DOC_MAX_FILE_MB = 1
    big = upload("big.pdf", PDF_BYTES + b"\x00" * (2 * 1024 * 1024))
    assert client.post(SUBMIT_URL, data=valid_payload(company_profile=big)).status_code == 400
    _assert_nothing_persisted()


def test_oversize_total_is_rejected(client, settings):
    settings.PARTNER_DOC_MAX_FILE_MB = 2
    settings.PARTNER_DOC_MAX_TOTAL_MB = 3
    a = upload("a.pdf", PDF_BYTES + b"\x00" * (1900 * 1024))
    b = upload("b.pdf", PDF_BYTES + b"\x00" * (1900 * 1024))
    resp = client.post(SUBMIT_URL, data=valid_payload(certificates=[a, b]))
    assert resp.status_code == 400
    _assert_nothing_persisted()


def test_too_many_files_is_rejected(client, settings):
    settings.PARTNER_DOC_MAX_FILES = 2
    files = [upload(f"c{i}.pdf", PDF_BYTES) for i in range(3)]
    assert client.post(SUBMIT_URL, data=valid_payload(certificates=files)).status_code == 400
    _assert_nothing_persisted()


def test_empty_file_is_rejected(client):
    assert client.post(
        SUBMIT_URL, data=valid_payload(logo=upload("empty.png", b""))
    ).status_code == 400
    _assert_nothing_persisted()


def test_one_bad_file_rejects_the_whole_submission(client):
    """Partial acceptance would leave a reviewer an incomplete application
    with no signal that anything was dropped."""
    good = upload("good.pdf", PDF_BYTES)
    bad = upload("bad.pdf", b"MZ\x90\x00")
    resp = client.post(SUBMIT_URL, data=valid_payload(company_profile=good, other_files=bad))
    assert resp.status_code == 400
    _assert_nothing_persisted()


# ═══ path traversal ══════════════════════════════════════════════════════════

def test_traversal_filename_cannot_escape_the_storage_root(client, isolated_private_storage):
    resp = client.post(
        SUBMIT_URL,
        data=valid_payload(commercial_register=upload("../../../../etc/passwd.pdf", PDF_BYTES)),
    )
    assert resp.status_code == 201, resp.content[:300]

    attachment = PartnerApplicationAttachment.objects.get()
    stored_path = Path(attachment.file.path).resolve()
    root = Path(isolated_private_storage).resolve()

    assert root in stored_path.parents, f"{stored_path} escaped {root}"
    assert ".." not in attachment.file.name
    assert "etc" not in attachment.file.name
    # The client name survives only as a display string, path-stripped.
    assert "/" not in attachment.original_filename


def test_stored_name_is_generated_not_the_client_name(client):
    resp = client.post(
        SUBMIT_URL, data=valid_payload(logo=upload("MyLogo.png", PNG_BYTES))
    )
    assert resp.status_code == 201
    attachment = PartnerApplicationAttachment.objects.get()
    assert "MyLogo" not in attachment.stored_filename
    assert attachment.stored_filename.endswith(".png")
    assert attachment.original_filename == "MyLogo.png"


def test_double_extension_cannot_smuggle_an_executable(client):
    resp = client.post(
        SUBMIT_URL, data=valid_payload(other_files=upload("payload.pdf.exe", PDF_BYTES))
    )
    assert resp.status_code == 400
    _assert_nothing_persisted()


# ═══ private storage ═════════════════════════════════════════════════════════

def test_documents_are_stored_outside_media_root(client):
    client.post(SUBMIT_URL, data=valid_payload(logo=upload("l.png", PNG_BYTES)))
    attachment = PartnerApplicationAttachment.objects.get()
    stored = Path(attachment.file.path).resolve()
    media = Path(settings.MEDIA_ROOT).resolve()
    assert media not in stored.parents, "partner documents must not live under MEDIA_ROOT"


def test_attachment_has_no_url_at_all(client):
    """base_url=None makes `.url` raise — an accidental template exposure
    fails loudly instead of quietly publishing a commercial registration."""
    client.post(SUBMIT_URL, data=valid_payload(logo=upload("l.png", PNG_BYTES)))
    attachment = PartnerApplicationAttachment.objects.get()
    with pytest.raises(Exception):
        _ = attachment.file.url


def test_document_is_not_reachable_anonymously_by_a_guessable_path(client):
    client.post(SUBMIT_URL, data=valid_payload(logo=upload("l.png", PNG_BYTES)))
    attachment = PartnerApplicationAttachment.objects.get()
    name = attachment.stored_filename

    for candidate in (
        f"/media/{name}",
        f"/media/partner_applications/{name}",
        f"/media/partners/{name}",
        f"/private_media/partner_applications/{name}",
        f"/static/{name}",
    ):
        resp = client.get(candidate)
        assert resp.status_code in (404, 403, 301, 302), (
            f"{candidate} returned {resp.status_code} — a partner document is web-reachable"
        )


# ═══ download authorisation ══════════════════════════════════════════════════

def _download_url(attachment):
    return f"/api/platform-admin/partner-attachments/{attachment.id}/download/"


def _make_attachment(client):
    client.post(SUBMIT_URL, data=valid_payload(commercial_register=upload("cr.pdf", PDF_BYTES)))
    return PartnerApplicationAttachment.objects.get()


def test_download_rejects_anonymous(client):
    attachment = _make_attachment(client)
    assert client.get(_download_url(attachment)).status_code in (401, 403)


def test_download_rejects_org_admin_role(client, org_admin_user):
    attachment = _make_attachment(client)
    client.force_login(org_admin_user)
    assert client.get(_download_url(attachment)).status_code == 403


def test_staff_download_serves_as_attachment(client, staff_user):
    attachment = _make_attachment(client)
    client.force_login(staff_user)
    resp = client.get(_download_url(attachment))

    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("attachment;")
    # Never a renderable/executable content type.
    assert resp["Content-Type"] == "application/octet-stream"
    assert resp["X-Content-Type-Options"] == "nosniff"


# ═══ throttling ══════════════════════════════════════════════════════════════

def test_application_endpoint_is_throttled(client):
    """The N+1th submission from one IP is refused.

    Exercises the REAL configured rate rather than overriding it: DRF caches
    DEFAULT_THROTTLE_RATES on api_settings, so reassigning settings.REST_FRAMEWORK
    mid-test does not necessarily reach the throttle — a test that appeared to
    pass that way could be asserting nothing. Distinct emails are used so
    duplicate-suppression (409) never masks the throttle (429).
    """
    from rest_framework.settings import api_settings

    rate = api_settings.DEFAULT_THROTTLE_RATES.get("partner_application")
    assert rate, "the partner_application throttle scope must be configured"
    limit = int(rate.split("/")[0])

    codes = []
    for i in range(limit + 2):
        resp = client.post(SUBMIT_URL, data=valid_payload(email=f"applicant{i}@example.com"))
        codes.append(resp.status_code)

    assert 429 in codes, f"never throttled at rate {rate}: {codes}"
    assert codes.index(429) <= limit, f"throttled later than the configured {rate}: {codes}"


def test_public_contact_form_is_throttled(client, settings):
    """B-8 from the Phase 0-A-PRE audit: an anonymous write path with no limit."""
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
            "public_contact": "2/day",
        },
    }
    from django.core.cache import cache
    cache.clear()

    from apps.leads.views import PublicContactFormView
    from rest_framework.throttling import ScopedRateThrottle

    assert ScopedRateThrottle in PublicContactFormView.throttle_classes
    assert PublicContactFormView.throttle_scope == "public_contact"


# ═══ declaration + duplicate suppression ═════════════════════════════════════

def test_declaration_is_required_server_side(client):
    payload = valid_payload()
    payload.pop("declaration_accepted")
    assert client.post(SUBMIT_URL, data=payload).status_code == 400
    assert PartnerApplication.objects.count() == 0


def test_declaration_false_is_rejected(client):
    assert client.post(
        SUBMIT_URL, data=valid_payload(declaration_accepted="false")
    ).status_code == 400
    assert PartnerApplication.objects.count() == 0


def test_duplicate_submission_within_the_window_is_refused(client):
    assert client.post(SUBMIT_URL, data=valid_payload()).status_code == 201
    second = client.post(SUBMIT_URL, data=valid_payload())
    assert second.status_code == 409
    assert PartnerApplication.objects.count() == 1


def test_unknown_business_area_is_rejected(client):
    assert client.post(
        SUBMIT_URL, data=valid_payload(business_areas=["erp", "time-travel"])
    ).status_code == 400


# ═══ happy path ══════════════════════════════════════════════════════════════

def test_valid_submission_with_every_file_type(client):
    resp = client.post(SUBMIT_URL, data=valid_payload(
        logo=upload("logo.png", PNG_BYTES),
        company_profile=upload("profile.pdf", PDF_BYTES),
        commercial_register=upload("cr.jpg", JPEG_BYTES),
        certificates=[upload("c1.pdf", PDF_BYTES), upload("c2.png", PNG_BYTES)],
    ))
    assert resp.status_code == 201, resp.content[:400]

    application = PartnerApplication.objects.get()
    assert application.status == ApplicationStatus.SUBMITTED
    assert application.attachments.count() == 5
    assert application.declaration_accepted is True
    # Submission metadata is server-derived.
    assert application.submitted_ip


def test_submission_records_detected_content_type_not_the_claimed_one(client):
    client.post(SUBMIT_URL, data=valid_payload(logo=upload("l.png", PNG_BYTES)))
    assert PartnerApplicationAttachment.objects.get().content_type == "image/png"


# ═══ applications have no public surface ═════════════════════════════════════

def test_applications_appear_on_no_public_page(client):
    client.post(SUBMIT_URL, data=valid_payload(company_name="Secret Applicant Co"))

    for url in (reverse("frontend:partners"), reverse("frontend:partner_apply")):
        body = client.get(url).content.decode()
        assert "Secret Applicant Co" not in body
        assert "apply@example.com" not in body


def test_application_public_fields_allowlist_is_empty():
    assert PartnerApplication.PUBLIC_FIELDS == ()
    application = PartnerApplication(company_name="X", email="x@example.com")
    assert application.public_payload() == {}


def test_anonymous_cannot_read_applications_through_the_admin_api(client):
    client.post(SUBMIT_URL, data=valid_payload())
    assert client.get("/api/platform-admin/partner-applications/").status_code in (401, 403)
