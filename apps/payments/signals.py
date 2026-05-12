"""Domain signals emitted by the payments app.

Other apps subscribe to these to wire the actual business action (mark
an invoice paid, activate a subscription, credit a wallet) without the
payments code importing them and creating a circular dep.
"""
from django.dispatch import Signal


# Fired exactly once per PaymentTransaction when it transitions to PAID.
# Args: transaction (PaymentTransaction), payload (dict)
payment_paid = Signal()
