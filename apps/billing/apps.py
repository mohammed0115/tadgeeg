from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.billing"
    verbose_name = "Billing & Subscriptions"

    def ready(self):
        # Hook payment-domain signals → subscription lifecycle.
        from apps.billing import receivers  # noqa: F401
