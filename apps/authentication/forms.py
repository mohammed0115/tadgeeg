"""Forms for email OTP verification flow."""

from django import forms


class EmailOTPVerifyForm(forms.Form):
    otp_code = forms.CharField(max_length=6, min_length=6)

    def clean_otp_code(self):
        otp_code = "".join(ch for ch in (self.cleaned_data.get("otp_code") or "") if ch.isdigit())
        if len(otp_code) != 6:
            raise forms.ValidationError("يرجى إدخال رمز تحقق مكوّن من 6 أرقام.")
        return otp_code


class EmailOTPResendForm(forms.Form):
    """Empty form kept for CSRF-protected resend requests."""

