from django.db import models


class PlanCode(models.TextChoices):
    FREE_TRIAL   = "free_trial",   "Free Trial"
    STARTER      = "starter",      "Starter"
    BUSINESS     = "business",     "Business"
    PROFESSIONAL = "professional", "Professional"


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
