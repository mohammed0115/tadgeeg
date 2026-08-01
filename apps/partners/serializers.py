"""Staff-facing partner serializer.

This is the ADMIN representation and includes the contact fields. It must never
be used for a public response — public output goes through
``Partner.public_payload()``, which is an allow-list.

``status`` is read-only here on purpose: publication is a state transition that
must be audited, so it happens through the publish/hide endpoints
(``apps.partners.services``) rather than as an incidental PATCH.
"""

from __future__ import annotations

from django.utils.text import slugify
from django_countries.serializer_fields import CountryField as DRFCountryField
from rest_framework import serializers

from .models import BusinessArea, Partner, PartnerApplication


class PartnerAdminSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()

    # Declared explicitly. ModelSerializer maps the model's CountryField to a
    # field that emits a `Country` OBJECT, which DRF's JSON encoder rejects with
    # "Object of type Country is not JSON serializable" — a 500 on create.
    #
    # This is the second time this exact trap has fired in this codebase: the
    # same type change broke the trial-users Excel export in Phase 1. Changing a
    # field's type changes its Python return type, and the migration shows
    # nothing. django-countries ships a DRF field that renders the alpha-2 code
    # while keeping ISO validation, so use it rather than a bare CharField.
    country = DRFCountryField(required=False, allow_blank=True)

    class Meta:
        model = Partner
        fields = [
            "id", "company_name", "slug",
            "logo", "logo_url", "country",
            "short_description", "long_description", "website",
            "partner_type", "partner_tier", "status",
            "contact_email", "contact_phone",
            "source_application", "display_order",
            "created_at", "updated_at", "published_at",
        ]
        read_only_fields = [
            "id", "created_at", "updated_at", "published_at",
            # Changing visibility must go through the audited endpoints.
            "status",
        ]
        extra_kwargs = {
            "slug": {"required": False},
            "logo": {"required": False},
        }

    def get_logo_url(self, obj) -> str:
        return obj.logo.url if obj.logo else ""

    def validate_slug(self, value):
        """Slugs are the public URL — collisions must be explicit, not silent."""
        value = (value or "").strip()
        if not value:
            return value
        queryset = Partner.objects.filter(slug=value)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                "A partner with this slug already exists. Slugs must be unique "
                "because they address the public detail page."
            )
        return value

    def create(self, validated_data):
        # Derive a slug when none was supplied, then make it unique by
        # suffixing rather than raising: an operator adding two partners with
        # similar names should not have to invent a slug by hand.
        if not validated_data.get("slug"):
            base = slugify(validated_data.get("company_name", "")) or "partner"
            candidate, counter = base, 2
            while Partner.objects.filter(slug=candidate).exists():
                candidate = f"{base}-{counter}"
                counter += 1
            validated_data["slug"] = candidate
        return super().create(validated_data)


# ─── Partner applications (Phase 2B, §E) ─────────────────────────────────────

class PartnerApplicationSubmitSerializer(serializers.ModelSerializer):
    """PUBLIC, UNAUTHENTICATED input. Treat every field as hostile.

    All validation is server-side. The form's `required` attributes are a
    convenience for humans and are not part of the contract — this serializer
    is.

    `status`, `reviewed_by`, `reviewed_at` and the submission metadata are NOT
    accepted from the client: they are set by the server. Listing only the
    submitter-supplied fields (rather than excluding the rest) means a field
    added to the model later is un-submittable by default.
    """

    business_areas = serializers.ListField(
        child=serializers.CharField(), allow_empty=True, required=False,
    )

    class Meta:
        model = PartnerApplication
        fields = [
            # §E.1
            "company_name", "contact_name", "position", "email", "mobile",
            "country", "city", "website", "established_year", "employee_count",
            # §E.2 / §E.3
            "requested_partner_type", "business_areas",
            # §E.4
            "company_summary", "partnership_reason", "key_clients", "years_experience",
            # §E.6
            "declaration_accepted",
        ]

    def validate_declaration_accepted(self, value):
        """§E.6 — mandatory, and enforced HERE, not in the template."""
        if value is not True:
            raise serializers.ValidationError(
                "You must confirm that the information provided is accurate."
            )
        return value

    def validate_business_areas(self, value):
        """Reject anything outside the fixed vocabulary.

        A JSON list column will happily store arbitrary strings, so the
        vocabulary has to be enforced here or not at all.
        """
        valid = set(BusinessArea.values)
        unknown = [v for v in value if v not in valid]
        if unknown:
            raise serializers.ValidationError(
                f"Unknown business areas: {', '.join(sorted(unknown))}."
            )
        # De-duplicate while preserving the submitted order.
        seen, ordered = set(), []
        for item in value:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered

    def validate_established_year(self, value):
        if value is None:
            return value
        from django.utils import timezone

        current = timezone.now().year
        if value < 1800 or value > current:
            raise serializers.ValidationError(
                f"Enter a founding year between 1800 and {current}."
            )
        return value

    def validate_mobile(self, value):
        raw = (value or "").strip()
        digits = [c for c in raw if c.isdigit()]
        if len(digits) < 8:
            raise serializers.ValidationError("Enter a valid mobile number.")
        if any(c not in "0123456789+ -()" for c in raw):
            raise serializers.ValidationError("Enter a valid mobile number.")
        return raw


class PartnerApplicationAdminSerializer(serializers.ModelSerializer):
    """STAFF-ONLY representation. Includes attachments and internal fields.

    Must never be reused on a public surface — applications have no public read
    path at all in this phase.
    """

    attachments = serializers.SerializerMethodField()
    notes = serializers.SerializerMethodField()
    reviewed_by_email = serializers.SerializerMethodField()
    country = DRFCountryField(required=False, allow_blank=True)

    class Meta:
        model = PartnerApplication
        fields = [
            "id", "company_name", "contact_name", "position", "email", "mobile",
            "country", "city", "website", "established_year", "employee_count",
            "requested_partner_type", "business_areas",
            "company_summary", "partnership_reason", "key_clients", "years_experience",
            "declaration_accepted", "status", "rejection_reason",
            "reviewed_by_email", "reviewed_at",
            "submitted_ip", "created_at", "updated_at",
            "attachments", "notes",
        ]
        read_only_fields = fields

    def get_reviewed_by_email(self, obj) -> str:
        return obj.reviewed_by.email if obj.reviewed_by else ""

    def get_attachments(self, obj) -> list:
        """Metadata only — never a URL.

        These files live on storage constructed with ``base_url=None``, so
        ``file.url`` would raise. Download goes through the staff-only endpoint
        that checks permission per request.
        """
        return [
            {
                "id": str(a.id),
                "file_type": a.file_type,
                "original_filename": a.original_filename,
                "size": a.size,
                "content_type": a.content_type,
                "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else "",
            }
            for a in obj.attachments.all()
        ]

    def get_notes(self, obj) -> list:
        return [
            {
                "id": str(n.id),
                "author": n.author.email if n.author else "",
                "note": n.note,
                "created_at": n.created_at.isoformat() if n.created_at else "",
            }
            for n in obj.notes.all()
        ]
