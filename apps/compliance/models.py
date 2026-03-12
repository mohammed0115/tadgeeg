import uuid
from django.db import models
from apps.authentication.models import Organization
from apps.transactions.models import Transaction

class ComplianceRule(models.Model):
    class Standard(models.TextChoices):
        ZATCA = "ZATCA", "ZATCA (Saudi e-invoicing)"
        VAT = "VAT", "VAT Regulations"
        IFRS = "IFRS", "IFRS"
        GAAP = "GAAP", "GAAP"
        SAMA = "SAMA", "Saudi Arabian Monetary Authority"
        INTERNAL = "INTERNAL", "Internal Policy"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=200)
    description = models.TextField()
    standard = models.CharField(max_length=20, choices=Standard.choices, default=Standard.INTERNAL)
    rule_expression = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = "compliance_rules"
    def __str__(self):
        return f"{self.standard}: {self.name}"

class ComplianceViolation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, null=True, blank=True)
    invoice = models.ForeignKey(
        "invoices.Invoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="compliance_violations",
    )
    rule_description = models.CharField(max_length=255)
    standard = models.CharField(max_length=20)
    severity = models.CharField(max_length=10, default="medium")
    description = models.TextField()
    corrective_action = models.TextField(blank=True)
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = "compliance_violations"
