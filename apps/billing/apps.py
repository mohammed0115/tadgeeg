from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.billing"
    verbose_name = "Billing & Subscriptions"

    def ready(self):
        # Hook payment-domain signals → subscription lifecycle.
        from apps.billing import receivers  # noqa: F401
        # Wrap the audit pipeline entry point with a quota gate so every
        # run_audit_compat call goes through reserve → consume / release.
        from apps.billing.quota_gate import install_gate
        install_gate()
