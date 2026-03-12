from django.contrib import admin


try:
    from .models import ComplianceRule, ComplianceViolation

    admin.site.register(ComplianceRule)
    admin.site.register(ComplianceViolation)
except ImportError:
    pass
