import uuid
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField


class ContactLead(models.Model):
    class Status(models.TextChoices):
        NEW = 'new', 'New'
        IN_PROGRESS = 'in_progress', 'In Progress'
        QUALIFIED = 'qualified', 'Qualified'
        CONVERTED = 'converted', 'Converted'
        CLOSED = 'closed', 'Closed'
        SPAM = 'spam', 'Spam'

    class Source(models.TextChoices):
        CONTACT_FORM = 'contact_form', 'Contact Form'
        PRICING_INQUIRY = 'pricing_inquiry', 'Pricing Inquiry'
        DEMO_REQUEST = 'demo_request', 'Demo Request'
        PARTNERSHIP = 'partnership', 'Partnership'
        OTHER = 'other', 'Other'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    company = models.CharField(max_length=200, blank=True)
    country = models.CharField(max_length=100, blank=True, default='Saudi Arabia')
    subject = models.CharField(max_length=300)
    message = models.TextField()
    source = models.CharField(max_length=30, choices=Source.choices, default=Source.CONTACT_FORM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_leads',
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Contact Lead'
        verbose_name_plural = 'Contact Leads'

    def __str__(self):
        return f"{self.full_name} ({self.email}) — {self.status}"


class LeadNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead = models.ForeignKey(ContactLead, on_delete=models.CASCADE, related_name='notes')
    note = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='lead_notes',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Lead Note'

    def __str__(self):
        return f"Note on {self.lead.full_name}"


class TrialLeadProfile(models.Model):
    """Marketing/lead metadata captured when a visitor registers for a trial.

    Deliberately NOT fields on ``User``:

    * ``User`` is load-bearing across the entire product; widening it for
      marketing attributes couples every auth path to lead capture.
    * The auto-captured block below is personal data (IP in particular) and
      needs one place to reason about retention and exposure. Keeping it in a
      single model means the retention policy has exactly one target — see
      ``docs/adr/0004-lead-metadata-privacy.md``.

    Deliberately NOT ``ContactLead``: that models an inbound *contact form*
    submission from an anonymous visitor. This models a *registered trial
    user*. They share the word "lead" and nothing else — different lifecycle,
    different owner, different retention.

    ``phone`` is not duplicated here: ``User.phone`` already exists and is made
    mandatory at the registration serializer, not on the model (other flows —
    staff creation, Google OAuth, fixtures — legitimately create users without
    one).
    """

    class PrimaryBenefit(models.TextChoices):
        """§A.2 — why the visitor wants Tadgeeg. Doubles as "client type" in
        the trial dashboard (decision D2).

        Single-select by design. The spec asks that the model not *block* a
        future move to multi-select, which a CharField does not: migrating to
        a through-table later keeps this column as the primary value. Adding a
        M2M now would ship unused complexity.
        """

        COMPANY = "company", _("Use it in my own company")
        RESELLER = "reseller", _("Offer the platform to other companies")
        ACCOUNTANT = "accountant", _("I am an accountant")
        TRAINER = "trainer", _("I am a trainer")

    class HeardAbout(models.TextChoices):
        GOOGLE = "google", _("Google")
        FACEBOOK = "facebook", _("Facebook")
        LINKEDIN = "linkedin", _("LinkedIn")
        FRIEND = "friend", _("A friend")
        PARTNER = "partner", _("A partner")
        OTHER = "other", _("Other")

    class EmployeeCount(models.TextChoices):
        """Banded rather than an exact integer: it is a segmentation input, and
        a band is both more honest (self-reported) and less identifying."""

        MICRO = "1-10", "1-10"
        SMALL = "11-50", "11-50"
        MEDIUM = "51-200", "51-200"
        LARGE = "201-500", "201-500"
        ENTERPRISE = "500+", "500+"

    class DeviceType(models.TextChoices):
        DESKTOP = "desktop", _("Desktop")
        MOBILE = "mobile", _("Mobile")
        TABLET = "tablet", _("Tablet")
        UNKNOWN = "unknown", _("Unknown")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trial_lead_profile",
    )

    # ── Contact (§A.1). country is required by the registration serializer;
    # the column allows blank so historical users and non-registration user
    # creation paths remain valid without a data migration.
    country = CountryField(
        blank=True,
        help_text=(
            "ISO 3166-1 alpha-2. Marketing qualification — where the prospect is. "
            "This is NOT Organization.country, which is the billing jurisdiction "
            "and stays restricted to the GCC members that map to a currency."
        ),
    )
    city = models.CharField(max_length=100, blank=True)
    company_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="As typed by the registrant, before organisation-name derivation.",
    )

    # ── Intent (§A.2) — required at the serializer, see country note above.
    primary_benefit = models.CharField(
        max_length=20, choices=PrimaryBenefit.choices, blank=True,
    )

    # ── Optional segmentation (§A.3)
    employee_count = models.CharField(
        max_length=10, choices=EmployeeCount.choices, blank=True,
    )
    sector = models.CharField(
        max_length=100, blank=True,
        help_text="Free text, mirroring Organization.industry.",
    )
    heard_about = models.CharField(
        max_length=20, choices=HeardAbout.choices, blank=True,
    )

    # ── Auto-capture (§A.4). Governed by §N — see ADR 0004.
    registered_ip = models.GenericIPAddressField(
        null=True, blank=True,
        help_text=(
            "Personal data. Purpose: fraud/abuse triage on trial signups. "
            "Staff-only — never serialised to a customer-facing surface."
        ),
    )
    device_type = models.CharField(
        max_length=10, choices=DeviceType.choices, default=DeviceType.UNKNOWN, blank=True,
    )
    language = models.CharField(
        max_length=10, blank=True, help_text="Active locale at registration, e.g. 'ar'.",
    )
    referral_source = models.CharField(
        max_length=100, blank=True,
        help_text="Referrer host only (e.g. 'google.com'). Never a full URL — §N data minimisation.",
    )
    campaign_source = models.CharField(
        max_length=100, blank=True,
        help_text="utm_source/utm_campaign value only. Never the full tracking URL.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Trial Lead Profile"
        verbose_name_plural = "Trial Lead Profiles"
        indexes = [
            # Drives the dashboard's group-by cards; all aggregation happens in
            # the DB, so these are the columns that get GROUP BY'd.
            models.Index(fields=["country"]),
            models.Index(fields=["primary_benefit"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"Trial lead: {self.user_id} ({self.country or '—'})"
