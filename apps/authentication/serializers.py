"""Authentication Serializers"""

from django.contrib.auth import authenticate
from django.utils import timezone
from datetime import timedelta
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User, Organization, OrganizationSettings


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

    class Meta:
        model = User
        fields = [
            "id", "email", "full_name", "role", "department", "phone",
            "organization", "organization_detail", "mfa_enabled",
            "is_active", "created_at", "last_login", "password",
        ]
        read_only_fields = ["id", "created_at", "last_login"]
        extra_kwargs = {
            "organization": {"write_only": True, "required": False, "allow_null": True},
        }

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        request = self.context.get("request")
        if not validated_data.get("organization") and request and getattr(request.user, "organization_id", None):
            validated_data["organization"] = request.user.organization
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
    password = serializers.CharField(write_only=True, min_length=8, style={"input_type": "password"})
    password_confirm = serializers.CharField(write_only=True, style={"input_type": "password"})
    organization_name = serializers.CharField(write_only=True, required=False)
    country = serializers.CharField(write_only=True, required=False, default="SA")

    class Meta:
        model = User
        fields = [
            "email", "full_name", "password", "password_confirm",
            "role", "organization_name", "country",
        ]

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        org_name = validated_data.pop("organization_name", None)
        country = validated_data.pop("country", "SA")

        organization = None
        if org_name:
            organization, _ = Organization.objects.get_or_create(
                name=org_name, defaults={"country": country}
            )

        user = User.objects.create_user(
            organization=organization,
            **validated_data,
        )
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError({"email": "Invalid credentials."})

        if user.is_locked():
            raise serializers.ValidationError(
                {"non_field_errors": "Account is temporarily locked. Please try again later."}
            )

        user_auth = authenticate(email=email, password=password)

        if not user_auth:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = timezone.now() + timedelta(minutes=30)
            user.save(update_fields=["failed_login_attempts", "locked_until"])
            raise serializers.ValidationError({"non_field_errors": "Invalid credentials."})

        if not user_auth.is_active:
            raise serializers.ValidationError({"non_field_errors": "Account is inactive."})

        # Reset failed attempts on success
        user_auth.failed_login_attempts = 0
        user_auth.locked_until = None
        user_auth.save(update_fields=["failed_login_attempts", "locked_until"])

        refresh = RefreshToken.for_user(user_auth)
        return {
            "user": user_auth,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    new_password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({"new_password": "Passwords do not match."})
        return attrs

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

# Re-export for views
from .serializers_extra import AuditLogSerializer
