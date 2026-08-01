"""Partner ecosystem (spec §C).

Type, tier and status are three independent fields. The original proposal
treated them as one list of five values, which §C.2 explicitly forbids: a
partner's *kind* of relationship, its *commercial level*, and its *record
state* answer different questions and change for different reasons.

"Strategic" appears in both ``PartnerType`` and ``PartnerTier`` on purpose. A
strategic partner is a distinct kind of relationship that also sits at the top
commercial level. Collapsing the two to remove the apparent duplication would
lose one of those facts.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField


def get_partner_document_storage():
    """Storage callable for attachment files.

    Referenced as a callable (not an instance) so the migration records a
    stable import path rather than a serialised absolute directory — the
    private root differs per environment and must be read from settings at
    runtime.
    """
    from .uploads import get_private_storage

    return get_private_storage()


class PartnerType(models.TextChoices):
    """Nature of the partnership. Drives the Distributors section (§D3)."""

    DISTRIBUTOR = "distributor", _("Authorized Distributor")
    TECHNICAL = "technical", _("Technical Partner")
    TRAINING = "training", _("Training Partner")
    STRATEGIC = "strategic", _("Strategic Partner")


class PartnerTier(models.TextChoices):
    """Commercial level. Drives the tier sections on the public page."""

    SILVER = "silver", _("Silver")
    GOLD = "gold", _("Gold")
    PLATINUM = "platinum", _("Platinum")
    STRATEGIC = "strategic", _("Strategic")


class PartnerStatus(models.TextChoices):
    """Record state. ONLY ``PUBLISHED`` is ever exposed publicly (§D4)."""

    DRAFT = "draft", _("Draft")
    PUBLISHED = "published", _("Published")
    HIDDEN = "hidden", _("Hidden")
    SUSPENDED = "suspended", _("Suspended")


class PublishedPartnerManager(models.Manager):
    """Publish gate at the DATA layer, not the template.

    A template-level ``{% if partner.status == 'published' %}`` is one
    refactor away from leaking drafts, and it cannot protect an API
    serializer or an export at all. Public code paths use
    ``Partner.published`` and physically cannot see anything else.
    """

    def get_queryset(self):
        return super().get_queryset().filter(status=PartnerStatus.PUBLISHED)


class Partner(models.Model):
    #: Fields safe to expose on a public surface. Everything absent from this
    #: tuple is internal. Notably contact_email / contact_phone: §C.4 and §N
    #: require an explicit policy or consent before publishing contact details,
    #: and no such policy exists — so they are stored and never served.
    PUBLIC_FIELDS = (
        "company_name",
        "slug",
        "country",
        "short_description",
        "long_description",
        "website",
        "partner_type",
        "partner_tier",
        "logo",
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ── Identity ────────────────────────────────────────────────────────
    company_name = models.CharField(max_length=200)
    slug = models.SlugField(
        max_length=120, unique=True,
        help_text="Used for /partners/<slug>/. Unique across all partners.",
    )

    # ── Public content ──────────────────────────────────────────────────
    logo = models.ImageField(
        upload_to="partners/logos/", blank=True, null=True,
        help_text=(
            "An approved partner logo is INTENDED to be public, so ordinary "
            "media storage is correct here. This is not the private-document "
            "path used for commercial registrations and certificates (Phase 2B)."
        ),
    )
    # Full ISO, not Organization.Country: a partner's country is descriptive,
    # not a billing jurisdiction. See 14-country-fix-report.md.
    country = CountryField(blank=True)
    short_description = models.CharField(
        max_length=300, blank=True, help_text="Card blurb on /partners/.",
    )
    long_description = models.TextField(blank=True, help_text="Detail page body.")
    website = models.URLField(blank=True)

    # ── Classification — three independent axes (§C.2 / D2) ─────────────
    partner_type = models.CharField(
        max_length=20, choices=PartnerType.choices, default=PartnerType.DISTRIBUTOR,
    )
    partner_tier = models.CharField(
        max_length=20, choices=PartnerTier.choices, blank=True,
        help_text=(
            "Commercial level. Blank is valid: a Technical or Training partner "
            "may hold no tier, in which case they have no public section."
        ),
    )
    status = models.CharField(
        max_length=20, choices=PartnerStatus.choices, default=PartnerStatus.DRAFT,
    )

    # ── Controlled — stored, never served publicly ──────────────────────
    contact_email = models.EmailField(
        blank=True,
        help_text="INTERNAL. Excluded from PUBLIC_FIELDS — §N requires consent to publish.",
    )
    contact_phone = models.CharField(
        max_length=30, blank=True,
        help_text="INTERNAL. Excluded from PUBLIC_FIELDS — §N requires consent to publish.",
    )

    # ── Provenance — placeholder for Phase 2B ───────────────────────────
    source_application = models.ForeignKey(
        "partners.PartnerApplication",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_partners",
        help_text=(
            "The application this partner was approved from, when there was one. "
            "SET_NULL rather than CASCADE: deleting an application must not "
            "delete a live published partner."
        ),
    )

    # ── Ordering ────────────────────────────────────────────────────────
    display_order = models.PositiveIntegerField(
        default=0, help_text="Card order within a tier. Lower shows first.",
    )

    # ── Audit ───────────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            "First time this partner was published. Hiding does NOT clear it — "
            "the original publication date stays available."
        ),
    )

    objects = models.Manager()
    published = PublishedPartnerManager()

    class Meta:
        ordering = ["display_order", "company_name"]
        verbose_name = "Partner"
        verbose_name_plural = "Partners"
        indexes = [
            models.Index(fields=["status", "partner_tier"]),
            models.Index(fields=["status", "partner_type"]),
            models.Index(fields=["slug"]),
        ]

    def __str__(self):
        return f"{self.company_name} ({self.partner_tier or self.partner_type}/{self.status})"

    # ── state transitions ───────────────────────────────────────────────

    def publish(self):
        """Make public. Stamps ``published_at`` only on first publication."""
        self.status = PartnerStatus.PUBLISHED
        fields = ["status", "updated_at"]
        if self.published_at is None:
            self.published_at = timezone.now()
            fields.append("published_at")
        self.save(update_fields=fields)
        return self

    def hide(self):
        """Remove from public surfaces, preserving the first-published date."""
        self.status = PartnerStatus.HIDDEN
        self.save(update_fields=["status", "updated_at"])
        return self

    @property
    def is_strategic(self) -> bool:
        """Hero placement is keyed on TIER, not type (§D3)."""
        return self.partner_tier == PartnerTier.STRATEGIC

    def public_payload(self) -> dict:
        """Allow-listed representation.

        Built by iterating PUBLIC_FIELDS rather than by excluding the private
        ones: a field added to the model later is private by default, which is
        the safe direction to fail.
        """
        payload = {}
        for field in self.PUBLIC_FIELDS:
            value = getattr(self, field, None)
            if field == "logo":
                payload["logo_url"] = value.url if value else ""
                continue
            if field == "country":
                payload["country"] = str(value or "")
                payload["country_name"] = value.name if value else ""
                continue
            payload[field] = value
        return payload


# ─── Partner applications (Phase 2B, §E) ─────────────────────────────────────

class BusinessArea(models.TextChoices):
    """§E.3 — multi-select. Stored as a JSON list of these values.

    A list column rather than a join table: these are a fixed vocabulary chosen
    on a form, never queried relationally, and never edited independently of
    their application. A through-table would add two models and a migration for
    no read we actually perform.
    """

    ERP = "erp", _("ERP")
    AUDIT = "audit", _("Auditing")
    ACCOUNTING = "accounting", _("Accounting")
    DIGITAL = "digital_transformation", _("Digital transformation")
    CYBERSECURITY = "cybersecurity", _("Cybersecurity")
    INFRASTRUCTURE = "infrastructure", _("Infrastructure")
    AI = "ai", _("Artificial intelligence")
    TRAINING = "training", _("Training")
    CONSULTING = "consulting", _("Consulting")
    SOFTWARE = "software_development", _("Software development")
    CLOUD = "cloud", _("Cloud services")


class ApplicationStatus(models.TextChoices):
    """§E.7 — the review state machine. Four states, no more.

    Legal transitions are enforced in apps.partners.services, not here and not
    in the UI: a model-level check cannot see who is acting or write the audit
    record that must accompany the change.
    """

    SUBMITTED = "submitted", _("Submitted")
    UNDER_REVIEW = "under_review", _("Under Review")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")


class PartnerApplication(models.Model):
    """An inbound partnership request from an anonymous visitor (§E).

    There is NO public read surface for this model. A submitter cannot retrieve
    their own application in this phase — the only exposure is the staff
    console. ``PUBLIC_FIELDS`` is therefore deliberately empty, and the
    allow-list helper below returns nothing: the safe default, and the same
    iterate-the-allow-list pattern Partner uses, so a field added later is
    private without anyone remembering to exclude it.
    """

    PUBLIC_FIELDS = ()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ── §E.1 company information (10 fields) ────────────────────────────
    company_name = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=200)
    position = models.CharField(max_length=120, blank=True)
    email = models.EmailField()
    mobile = models.CharField(max_length=30)
    country = CountryField()
    city = models.CharField(max_length=120, blank=True)
    website = models.URLField(blank=True)
    established_year = models.PositiveIntegerField(null=True, blank=True)
    employee_count = models.CharField(max_length=20, blank=True)

    # ── §E.2 requested partnership type ─────────────────────────────────
    requested_partner_type = models.CharField(
        max_length=20, choices=PartnerType.choices,
        help_text="What the applicant asked for. The reviewer decides the actual type and tier.",
    )

    # ── §E.3 business areas (multi-select) ──────────────────────────────
    business_areas = models.JSONField(
        default=list, blank=True,
        help_text="List of BusinessArea values. Validated at the serializer.",
    )

    # ── §E.4 additional information ─────────────────────────────────────
    company_summary = models.TextField(blank=True)
    partnership_reason = models.TextField(blank=True)
    key_clients = models.TextField(blank=True)
    years_experience = models.PositiveIntegerField(null=True, blank=True)

    # ── §E.6 declaration ────────────────────────────────────────────────
    declaration_accepted = models.BooleanField(
        default=False,
        help_text="§E.6 — required. Enforced server-side at the serializer, not just the form.",
    )

    # ── review ──────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=20, choices=ApplicationStatus.choices,
        default=ApplicationStatus.SUBMITTED,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="reviewed_partner_applications",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(
        blank=True,
        help_text="INTERNAL. Not echoed verbatim in outbound email.",
    )

    # ── submission metadata (§N — same minimisation rules as lead capture) ─
    submitted_ip = models.GenericIPAddressField(
        null=True, blank=True,
        help_text="Personal data. Abuse triage only. Staff-only; never served publicly.",
    )
    submitted_user_agent = models.CharField(max_length=300, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Partner Application"
        verbose_name_plural = "Partner Applications"
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["email"]),
            models.Index(fields=["country"]),
        ]

    def __str__(self):
        return f"{self.company_name} ({self.status})"

    def public_payload(self) -> dict:
        """Empty by construction — applications have no public surface."""
        return {field: getattr(self, field) for field in self.PUBLIC_FIELDS}


class PartnerApplicationAttachment(models.Model):
    """A document submitted with an application (§E.5).

    Stored on PRIVATE storage outside MEDIA_ROOT — see apps.partners.uploads.
    ``file.url`` RAISES for these, by design.
    """

    class FileType(models.TextChoices):
        LOGO = "logo", _("Company logo")
        PROFILE = "profile", _("Company profile")
        COMMERCIAL_REGISTER = "commercial_register", _("Commercial registration")
        CERTIFICATE = "certificate", _("Certificate")
        OTHER = "other", _("Other")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        PartnerApplication, on_delete=models.CASCADE, related_name="attachments",
    )
    file = models.FileField(
        upload_to="",
        storage=get_partner_document_storage,
        help_text=(
            "Private storage outside MEDIA_ROOT. `.url` RAISES by design — retrieval "
            "is the staff-only download endpoint. See apps/partners/uploads.py."
        ),
    )
    file_type = models.CharField(max_length=30, choices=FileType.choices, default=FileType.OTHER)
    original_filename = models.CharField(
        max_length=200,
        help_text="DISPLAY ONLY. Never used as the on-disk name — see uploads.safe_stored_name.",
    )
    stored_filename = models.CharField(max_length=120)
    size = models.PositiveIntegerField(default=0)
    content_type = models.CharField(
        max_length=100, blank=True,
        help_text="Detected from the file's actual bytes, not from its extension.",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]
        verbose_name = "Partner Application Attachment"
        verbose_name_plural = "Partner Application Attachments"

    def __str__(self):
        return f"{self.original_filename} ({self.file_type})"


class PartnerApplicationNote(models.Model):
    """Reviewer note. INTERNAL — never served on any public surface."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        PartnerApplication, on_delete=models.CASCADE, related_name="notes",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name="partner_application_notes",
    )
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Partner Application Note"

    def __str__(self):
        return f"Note on {self.application_id}"
