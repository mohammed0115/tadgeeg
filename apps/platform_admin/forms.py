"""
Platform CRM forms (CRM-1E).

Explicit, whitelisted forms — NOT open ModelForms — so callers can never inject
``created_by``, ``status``, ``resolved_at``, or any field outside the intended
input set. Server-side services apply the authoritative business rules; these
forms validate shape and choices.
"""

from decimal import Decimal

from django import forms

from apps.authentication.models import Organization
from apps.billing.models import Plan
from apps.platform_admin import selectors
from apps.platform_admin.models import CustomerNote, SupportTicket  # noqa: F401


class CreateSupportTicketForm(forms.Form):
    organization = forms.ModelChoiceField(
        queryset=Organization.objects.all().order_by("name"),
        required=True,
    )
    title = forms.CharField(max_length=255, required=True)
    category = forms.ChoiceField(
        choices=SupportTicket.Category.choices,
        initial=SupportTicket.Category.GENERAL,
        required=True,
    )
    priority = forms.ChoiceField(
        choices=SupportTicket.Priority.choices,
        initial=SupportTicket.Priority.MEDIUM,
        required=True,
    )
    description = forms.CharField(widget=forms.Textarea, required=True)
    assigned_to = forms.ModelChoiceField(
        queryset=selectors.get_assignable_crm_staff(),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Re-evaluate the staff queryset per-request (membership can change).
        self.fields["assigned_to"].queryset = selectors.get_assignable_crm_staff()

    def clean_title(self):
        return self.cleaned_data["title"].strip()

    def clean_description(self):
        return self.cleaned_data["description"].strip()


class TicketMessageForm(forms.Form):
    message = forms.CharField(widget=forms.Textarea, required=True)
    internal_only = forms.BooleanField(required=False)

    def clean_message(self):
        text = self.cleaned_data["message"].strip()
        if not text:
            raise forms.ValidationError("Message text is required.")
        return text


class TicketStatusUpdateForm(forms.Form):
    status = forms.ChoiceField(choices=SupportTicket.Status.choices, required=True)
    reason = forms.CharField(widget=forms.Textarea, required=True)

    def clean_reason(self):
        text = self.cleaned_data["reason"].strip()
        if not text:
            raise forms.ValidationError("A reason is required.")
        return text


class TicketAssignForm(forms.Form):
    assigned_to = forms.ModelChoiceField(
        queryset=selectors.get_assignable_crm_staff(),
        required=False,  # blank = unassign
    )
    reason = forms.CharField(widget=forms.Textarea, required=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = selectors.get_assignable_crm_staff()

    def clean_reason(self):
        text = self.cleaned_data["reason"].strip()
        if not text:
            raise forms.ValidationError("A reason is required.")
        return text


# Operational safety cap: extend by at most ~2 years in one action. A larger
# change should be a deliberate, repeated action — not a single huge jump.
MAX_EXTEND_DAYS = 730


class ExtendSubscriptionForm(forms.Form):
    """Whitelisted: only days + reason. Plan/status/quota cannot be touched."""

    days = forms.IntegerField(min_value=1, max_value=MAX_EXTEND_DAYS)
    reason = forms.CharField(widget=forms.Textarea, max_length=500, required=True)

    def clean_reason(self):
        text = self.cleaned_data["reason"].strip()
        if not text:
            raise forms.ValidationError("A reason is required.")
        return text


class FinancialReasonForm(forms.Form):
    """Reason-only form for suspend/reactivate and manual-payment confirm/reject.
    No other field is accepted — subscription/plan/quota/payment cannot be touched."""

    reason = forms.CharField(widget=forms.Textarea, max_length=500, required=True)

    def clean_reason(self):
        text = self.cleaned_data["reason"].strip()
        if not text:
            raise forms.ValidationError("A reason is required.")
        return text


class ManualPaymentAddForm(forms.Form):
    """Whitelisted manual-payment input: plan + amount + currency + reference +
    reason ONLY. status/provider/user/raw data can never be injected. The
    authoritative amount==plan.price / currency==plan.currency check is enforced
    server-side by the payment service (this form only validates shape)."""

    plan = forms.ModelChoiceField(queryset=Plan.objects.none(), required=True)
    amount = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01"), required=True
    )
    currency = forms.CharField(min_length=3, max_length=3, required=True)
    reference = forms.CharField(max_length=128, required=True)
    reason = forms.CharField(widget=forms.Textarea, max_length=500, required=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plan"].queryset = selectors.get_purchasable_plans()

    def clean_currency(self):
        return self.cleaned_data["currency"].strip().upper()

    def clean_reference(self):
        text = self.cleaned_data["reference"].strip()
        if not text:
            raise forms.ValidationError("A payment reference is required.")
        return text

    def clean_reason(self):
        text = self.cleaned_data["reason"].strip()
        if not text:
            raise forms.ValidationError("A reason is required.")
        return text


class WhatsAppBusinessNumberForm(forms.Form):
    """Global public contact number; never the Meta phone-number ID or token."""

    business_number = forms.CharField(max_length=16, required=False)

    def clean_business_number(self):
        value = self.cleaned_data["business_number"].strip().replace(" ", "")
        if not value:
            return ""
        from core.services.whatsapp import validate_recipient, WhatsAppUnavailable

        try:
            return validate_recipient(value)
        except WhatsAppUnavailable as exc:
            raise forms.ValidationError(
                "Use E.164 format, for example +966501234567."
            ) from exc
