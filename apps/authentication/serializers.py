"""Authentication Serializers"""

from datetime import timedelta
from django.db import transaction

from django.contrib.auth import authenticate
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from django_countries import countries

from apps.leads.models import TrialLeadProfile

from .models import User, Organization, OrganizationSettings
from .services.organization_setup import ensure_user_organization


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = [
            "id", "name", "name_ar", "country", "currency",
            "vat_number", "cr_number", "vat_rate", "industry",
            "fiscal_year_start", "address", "website", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class OrganizationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationSettings
        fields = ["id", "organization", "financial", "notifications", "created_at", "updated_at"]
        read_only_fields = ["id", "organization", "created_at", "updated_at"]


class UserSerializer(serializers.ModelSerializer):
    organization_detail = OrganizationSerializer(source="organization", read_only=True)
    password = serializers.CharField(write_only=True, required=False, min_length=8)
    is_email_verified = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "email", "full_name", "role", "department", "phone",
            "organization", "organization_detail", "mfa_enabled",
            "is_active", "is_email_verified", "email_verified_at",
            "created_at", "last_login", "password",
        ]
        read_only_fields = ["id", "is_email_verified", "email_verified_at", "created_at", "last_login"]
        extra_kwargs = {
            "organization": {"write_only": True, "required": False, "allow_null": True},
        }

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        request = self.context.get("request")
        if not validated_data.get("organization") and request and getattr(request.user, "organization_id", None):
            validated_data["organization"] = request.user.organization
        validated_data.setdefault("email_verified_at", timezone.now())
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class RegisterSerializer(serializers.ModelSerializer):
    """Trial registration — also the lead-capture entry point (spec §A).

    Both registration surfaces run through here (the DRF endpoint
    ``apps/authentication/views.RegisterView`` and the HTML form handler
    ``apps/frontend/page_views.register_view``), so validation lives here and
    neither surface can be bypassed by posting directly to the other.

    ``role`` is left assigned to ``User.Role.ADMIN`` on purpose: it marks the
    *organisation* owner, and owner detection, ``effective_role`` and
    ``is_org_admin`` all depend on it.
    """

    password = serializers.CharField(write_only=True, min_length=8, style={"input_type": "password"})
    password_confirm = serializers.CharField(write_only=True, style={"input_type": "password"})
    organization_name = serializers.CharField(write_only=True, required=False)

    # ── §A.1 required contact data ───────────────────────────────────────
    # phone lands on User.phone, which stays blank=True at the model level:
    # staff creation, Google OAuth and fixtures legitimately create users
    # without a phone. Mandatory *here* only, where a human is filling a form.
    phone = serializers.CharField(write_only=True, max_length=20, allow_blank=False)
    # Full ISO 3166-1 alpha-2, NOT Organization.Country.
    #
    # These are two different questions that happen to share a word:
    #   Organization.country  = billing jurisdiction, pairs 1:1 with a currency,
    #                           so it is legitimately restricted to the GCC.
    #   lead country (§A.1)   = where the prospect is, for marketing
    #                           qualification. Restricting it to six countries
    #                           made non-GCC prospects unable to register at all.
    #
    # ContactLead.country was already a free CharField, so the contact form has
    # always accepted any country — restricting *trial* registration was
    # inconsistent even within apps/leads.
    country = serializers.ChoiceField(
        write_only=True, choices=list(countries),
    )
    city = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=100)
    company_name = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=200,
    )

    # ── §A.2 required intent (also "client type" on the trial dashboard) ──
    primary_benefit = serializers.ChoiceField(
        write_only=True, choices=TrialLeadProfile.PrimaryBenefit.choices,
    )

    # ── §A.3 optional segmentation ───────────────────────────────────────
    employee_count = serializers.ChoiceField(
        write_only=True, required=False, allow_blank=True,
        choices=TrialLeadProfile.EmployeeCount.choices,
    )
    sector = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=100)
    heard_about = serializers.ChoiceField(
        write_only=True, required=False, allow_blank=True,
        choices=TrialLeadProfile.HeardAbout.choices,
    )

    class Meta:
        model = User
        fields = [
            "email", "full_name", "password", "password_confirm",
            "role", "organization_name",
            "phone", "country", "city", "company_name",
            "primary_benefit", "employee_count", "sector", "heard_about",
        ]

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password": _("Passwords do not match.")})
        return attrs

    def validate_phone(self, value):
        """Format check only — no carrier or country-code assumptions.

        The registrant base spans the GCC, so anything stricter than "enough
        digits, sane characters" would reject legitimate numbers.
        """
        raw = (value or "").strip()
        digits = [c for c in raw if c.isdigit()]
        if len(digits) < 8:
            raise serializers.ValidationError(_("Enter a valid phone number."))
        if any(c not in "0123456789+ -()" for c in raw):
            raise serializers.ValidationError(_("Enter a valid phone number."))
        return raw

    def create(self, validated_data):
        from apps.leads.services import TRIAL_LEAD_INPUT_FIELDS, create_trial_lead_profile

        org_name = validated_data.pop("organization_name", None)
        # Pulled out before create_user(): these belong to the lead profile,
        # not to the User row.
        lead_data = {
            field: validated_data.pop(field, "")
            for field in TRIAL_LEAD_INPUT_FIELDS
        }
        # company_name is captured raw for the lead record, and also seeds the
        # organisation name when the registrant gave no explicit one.
        lead_data["company_name"] = lead_data.get("company_name") or (org_name or "")
        validated_data["role"] = User.Role.ADMIN

        # ── lead country vs billing jurisdiction — keep these separate ───────
        # The form asks ONE question, but the answer feeds two fields with
        # different domains:
        #
        #   lead_data["country"]  — any ISO country. Stored verbatim on the
        #                           TrialLeadProfile for marketing qualification.
        #   billing_country       — must be a member of Organization.Country,
        #                           because Organization.currency is derived
        #                           from it (COUNTRY_CURRENCY_MAP).
        #
        # A GCC answer flows into both, preserving the behaviour every existing
        # customer already has. A non-GCC answer flows ONLY into the lead
        # profile: that prospect has no supported billing currency yet, and
        # recording a false jurisdiction is worse than recording none — it would
        # silently mis-derive their currency. Billing jurisdiction is settled
        # later, at subscription time.
        #
        # Do NOT collapse these back into one variable. ensure_user_organization
        # also guards (organization_setup.py — `safe_country`), but relying on a
        # downstream fallback to launder an invalid value hides the intent.
        lead_country = lead_data.get("country") or ""
        billing_country = (
            lead_country
            if lead_country in Organization.Country.values
            else Organization.Country.SAUDI_ARABIA
        )

        # One transaction across user + organisation + lead profile. A failure
        # writing the lead profile must not leave a half-registered user.
        with transaction.atomic():
            user = User.objects.create_user(
                organization=None,
                email_verified_at=None,
                **validated_data,
            )
            ensure_user_organization(
                user,
                organization_name=org_name or lead_data.get("company_name") or "",
                country=billing_country,
                promote_owner=True,
            )
            create_trial_lead_profile(
                user,
                lead_data=lead_data,
                request=self.context.get("request"),
            )
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = (attrs.get("email") or "").strip().lower()
        password = attrs.get("password")
        attrs["email"] = email

        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise serializers.ValidationError({"email": _("No account found with this email address.")})

        if user.is_locked():
            raise serializers.ValidationError(
                {"non_field_errors": _("Account is temporarily locked. Please try again later.")}
            )

        user_auth = authenticate(email=user.email, password=password)

        if not user_auth:
            # Atomic counter — F() so two parallel wrong-password attempts
            # both register, instead of racing for the same "current + 1".
            from django.db.models import F
            User.objects.filter(pk=user.pk).update(
                failed_login_attempts=F("failed_login_attempts") + 1
            )
            user.refresh_from_db(fields=["failed_login_attempts"])
            if user.failed_login_attempts >= 5:
                User.objects.filter(pk=user.pk).update(
                    locked_until=timezone.now() + timedelta(minutes=30)
                )
            raise serializers.ValidationError({"non_field_errors": _("Invalid credentials.")})

        if not user_auth.is_active:
            raise serializers.ValidationError({"non_field_errors": _("Account is inactive.")})

        # Reset failed attempts on success — atomic write.
        User.objects.filter(pk=user_auth.pk).update(
            failed_login_attempts=0,
            locked_until=None,
        )

        return {
            "user": user_auth,
        }


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    new_password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({"new_password": _("Passwords do not match.")})
        return attrs

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError(_("Current password is incorrect."))
        return value

# Re-export for views
from .serializers_extra import AuditLogSerializer
