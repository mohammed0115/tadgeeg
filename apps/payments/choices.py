from django.db import models


class PaymentProvider(models.TextChoices):
    MOYASAR = "moyasar", "Moyasar"
    TAP     = "tap",     "Tap Payments"
    TELR    = "telr",    "Telr"


class PaymentPurpose(models.TextChoices):
    SUBSCRIPTION  = "subscription",  "Subscription"
    INVOICE       = "invoice",       "Invoice"
    SERVICE_ORDER = "service_order", "Service Order"
    WALLET_TOPUP  = "wallet_topup",  "Wallet Top-Up"
    OTHER         = "other",         "Other"


class PaymentStatus(models.TextChoices):
    """Internal status — provider-specific statuses are mapped to these via
    ``BasePaymentGateway.map_provider_status`` so the business layer never
    has to know which provider it's talking to."""
    PENDING            = "pending",            "Pending"            # row created, gateway not called yet
    INITIATED          = "initiated",          "Initiated"          # gateway accepted the request
    REDIRECT_REQUIRED  = "redirect_required",  "Redirect Required"  # user must complete payment off-site
    PAID               = "paid",               "Paid"               # confirmed via webhook OR retrieve_payment
    FAILED             = "failed",             "Failed"
    CANCELED           = "canceled",           "Canceled"
    EXPIRED            = "expired",            "Expired"
    REFUNDED           = "refunded",           "Refunded"
    PARTIALLY_REFUNDED = "partially_refunded", "Partially Refunded"


# Terminal statuses that must not be transitioned away from idempotently.
TERMINAL_STATUSES = frozenset({
    PaymentStatus.PAID,
    PaymentStatus.FAILED,
    PaymentStatus.CANCELED,
    PaymentStatus.EXPIRED,
    PaymentStatus.REFUNDED,
    PaymentStatus.PARTIALLY_REFUNDED,
})

# Statuses considered "successful payment" for business action purposes.
PAID_STATUSES = frozenset({PaymentStatus.PAID})
