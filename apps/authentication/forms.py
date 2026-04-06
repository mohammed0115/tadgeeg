"""Forms for authentication and email OTP flows."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.utils.translation import gettext_lazy as _


User = get_user_model()


class EmailOTPVerifyForm(forms.Form):
    otp_code = forms.CharField(
        max_length=6,
        min_length=6,
        label=_("Verification Code"),
    )

    def clean_otp_code(self):
        otp_code = "".join(ch for ch in (self.cleaned_data.get("otp_code") or "") if ch.isdigit())
        if len(otp_code) != 6:
            raise forms.ValidationError(_("Please enter a 6-digit verification code."))
        return otp_code


class EmailOTPResendForm(forms.Form):
    """Empty form kept for CSRF-protected resend requests."""


class ExistingEmailPasswordResetForm(PasswordResetForm):
    """Require the submitted email to belong to an active user account."""

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not User.objects.filter(email__iexact=email, is_active=True).exists():
            raise forms.ValidationError(_("No active account was found with this email address."))
        return email
