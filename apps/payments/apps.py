from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payments"
    verbose_name = "Payments"

    def ready(self):
        # Validate PAYMENT_PROVIDER at boot — fail fast on misconfig.
        from apps.payments.gateways import factory  # noqa: F401
        factory.validate_configured_provider()
        # Connect built-in receivers (purpose fan-out, invoice settling).
        from apps.payments import receivers  # noqa: F401
