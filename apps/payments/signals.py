"""Domain signals emitted by the payments app.

Other apps subscribe to these to wire the actual business action (mark
an invoice paid, activate a subscription, credit a wallet) without the
payments code importing them and creating a circular dep.
"""
from django.dispatch import Signal


# Fired exactly once per PaymentTransaction when it transitions to PAID.
# Args: transaction (PaymentTransaction), payload (dict)
payment_paid = Signal()

# Fired exactly once per PaymentTransaction when it transitions to FAILED.
# Args: transaction (PaymentTransaction), reason (str), payload (dict)
payment_failed = Signal()

# Purpose-typed signals — downstream apps subscribe to the one they care
# about and don't have to inspect transaction.purpose themselves.
# Args: transaction (PaymentTransaction), payload (dict)
subscription_paid  = Signal()
invoice_paid       = Signal()
service_order_paid = Signal()
wallet_topped_up   = Signal()

