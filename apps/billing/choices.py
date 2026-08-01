from django.db import models
from django.utils.translation import gettext_lazy as _


class PlanCode(models.TextChoices):
    """The nine catalogue codes (spec §H and §J).

    Two families:
      * business plans — free_trial → enterprise
      * accounting-firm plans — for practices managing multiple client companies

    Order here is the commercial ladder, and ``sort_order`` on the seeded rows
    mirrors it. ``enterprise`` and ``accounting_enterprise`` carry no list
    price: they are ``is_custom_quote`` and are NOT purchasable through
    self-service checkout.
    """

    FREE_TRIAL   = "free_trial",   "Free Trial"
    STARTER      = "starter",      "Starter"
    BASIC        = "basic",        "Basic"
    BUSINESS     = "business",     "Business"
    PROFESSIONAL = "professional", "Professional"
    ENTERPRISE   = "enterprise",   "Enterprise"

    ACCOUNTING_PARTNER      = "accounting_partner",      "Accounting Partner"
    ACCOUNTING_PROFESSIONAL = "accounting_professional", "Accounting Professional"
    ACCOUNTING_ENTERPRISE   = "accounting_enterprise",   "Accounting Enterprise"


#: Codes belonging to the accounting-firm family. The pricing page shows these
#: in their own section (§L.4) rather than mixed into the main row.
ACCOUNTING_PLAN_CODES = frozenset({
    PlanCode.ACCOUNTING_PARTNER,
    PlanCode.ACCOUNTING_PROFESSIONAL,
    PlanCode.ACCOUNTING_ENTERPRISE,
})


class SubscriptionStatus(models.TextChoices):
    TRIALING        = "trialing",        "Trialing"
    PENDING_PAYMENT = "pending_payment", "Pending Payment"
    ACTIVE          = "active",          "Active"
    EXPIRED         = "expired",         "Expired"
    CANCELED        = "canceled",        "Canceled"
    PAYMENT_FAILED  = "payment_failed",  "Payment Failed"


# Statuses that count as "the org has a usable subscription right now".
USABLE_STATUSES = frozenset({
    SubscriptionStatus.TRIALING,
    SubscriptionStatus.ACTIVE,
})


class UsageAction(models.TextChoices):
    RESERVE = "reserve", "Reserve"
    CONSUME = "consume", "Consume"
    RELEASE = "release", "Release"
    REFUND  = "refund",  "Refund"


class AddonBillingType(models.TextChoices):
    """§I insists these are three billing types, never one.

    Modelling one and flagging the rest is the failure mode the spec names
    explicitly: «لا تعامل هذه الثلاثة كنوع billing واحد». The type is what
    drives renewal, so it is a column and not a convention.
    """

    RECURRING = "recurring", _("Recurring")
    ONE_TIME = "one_time", _("One-time")
    CUSTOM_QUOTE = "custom_quote", _("Custom quote")


class AddonDimension(models.TextChoices):
    """Which ceiling an add-on raises, if any.

    A professional service (training, an integration) raises nothing — it is
    billable but grants no quota, and conflating that with a quota pack would
    silently inflate someone's allowance.
    """

    USERS = "users", _("Users")
    INVOICES = "invoices", _("Invoices")
    NONE = "none", _("No quota")
