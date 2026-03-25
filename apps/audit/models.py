"""Audit App — Cases, workflow, and case management"""

import uuid
from django.db import models
from apps.authentication.models import User, Organization
from apps.transactions.models import Transaction


class AuditSession(models.Model):
    """Tracks the lifecycle and aggregate progress of a related audit upload."""

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        EXTRACTING = "extracting", "Extracting"
        NORMALIZING = "normalizing", "Normalizing"
        VALIDATING = "validating", "Validating"
        REVIEW_REQUIRED = "review_required", "Review Required"
        ACTION_REQUIRED = "action_required", "Action Required"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="audit_sessions",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_audit_sessions",
    )
    name = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RECEIVED,
    )
    total_count = models.PositiveIntegerField(default=0)
    processed_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    review_required_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    high_risk_count = models.PositiveIntegerField(default=0)
    average_risk_score = models.FloatField(default=0.0)
    max_risk_score = models.FloatField(default=0.0)
    last_error = models.TextField(blank=True)
    context = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # ── Soft Delete (GDPR Compliance) ─────────────────────────────────────────
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="deleted_audit_sessions"
    )

    class Meta:
        db_table = "audit_sessions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        label = self.name or str(self.id)
        return f"AuditSession {label} ({self.status})"

    @property
    def progress_percent(self):
        if not self.total_count:
            return 0
        return round((self.processed_count / self.total_count) * 100, 2)

    def get_descendants_soft_deleted_count(self) -> int:
        """Count invoices and findings that would be affected by soft delete."""
        from apps.invoices.models import Invoice
        count = (
            Invoice.objects.filter(audit_session=self, is_deleted=False).count() +
            self.audit_findings.filter(is_deleted=False).count()
        )
        return count

    def delete(self, *args, **kwargs):
        """Override delete() to perform soft delete (GDPR Article 17)."""
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if 'user' in kwargs:
            self.deleted_by = kwargs.pop('user')
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by', 'updated_at'])


class AuditFinding(models.Model):
    """Persisted user-facing findings generated from validation and review workflows."""

    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"
        IGNORED = "ignored", "Ignored"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="audit_findings",
    )
    audit_session = models.ForeignKey(
        AuditSession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="findings",
    )
    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_findings",
    )
    invoice = models.ForeignKey(
        "invoices.Invoice",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="audit_findings",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_audit_findings",
    )
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_audit_findings",
    )
    rule_code = models.CharField(max_length=20)
    rule_name = models.CharField(max_length=255)
    rule_group = models.CharField(max_length=10, blank=True)
    severity = models.CharField(
        max_length=10,
        choices=Severity.choices,
        default=Severity.MEDIUM,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    message = models.TextField()
    details = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=50, default="validation_engine")
    first_detected_at = models.DateTimeField(auto_now_add=True)
    last_detected_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "audit_findings"
        ordering = ["-last_detected_at"]
        indexes = [
            models.Index(fields=["organization", "status", "severity"]),
            models.Index(fields=["audit_session", "status"]),
            models.Index(fields=["invoice", "rule_code"]),
        ]

    def __str__(self):
        return f"{self.rule_code} ({self.severity})"


class AuditCase(models.Model):
    """An audit case created from an anomaly or manual finding."""

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class CaseStatus(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        UNDER_REVIEW = "under_review", "Under Review"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"
        ESCALATED = "escalated", "Escalated"

    class CaseType(models.TextChoices):
        ANOMALY = "anomaly", "Transaction Anomaly"
        FRAUD = "fraud", "Suspected Fraud"
        COMPLIANCE = "compliance", "Compliance Violation"
        DUPLICATE = "duplicate", "Duplicate Transaction"
        MANUAL = "manual", "Manual Finding"
        BENFORD = "benford", "Benford's Law Violation"
        JOURNAL = "journal", "Suspicious Journal Entry"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="audit_cases")
    case_number = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=255)
    description = models.TextField()
    case_type = models.CharField(max_length=20, choices=CaseType.choices, default=CaseType.ANOMALY)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=20, choices=CaseStatus.choices, default=CaseStatus.OPEN)
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_cases"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="created_cases"
    )
    transaction = models.ForeignKey(
        Transaction, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_cases"
    )
    invoice = models.ForeignKey(
        "invoices.Invoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_cases",
    )
    ai_risk_score = models.FloatField(default=0.0)
    ai_findings = models.JSONField(default=dict)
    due_date = models.DateField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="resolved_cases"
    )
    tags = models.JSONField(default=list)
    attachments = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # ── Soft Delete (GDPR Compliance) ─────────────────────────────────────────
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="deleted_audit_cases"
    )

    class Meta:
        db_table = "audit_cases"
        ordering = ["-priority", "-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["assigned_to"]),
            models.Index(fields=["priority"]),
        ]

    def __str__(self):
        return f"{self.case_number}: {self.title}"

    def save(self, *args, **kwargs):
        if not self.case_number:
            import datetime
            count = AuditCase.objects.filter(organization=self.organization).count()
            year = datetime.datetime.now().year
            self.case_number = f"CASE-{year}-{count + 1:04d}"
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Override delete() to perform soft delete (GDPR Article 17)."""
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if 'user' in kwargs:
            self.deleted_by = kwargs.pop('user')
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by', 'updated_at'])


class CaseComment(models.Model):
    """Comment on an audit case."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(AuditCase, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    text = models.TextField()
    is_internal = models.BooleanField(default=False, help_text="Internal note not visible to external auditors")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "case_comments"
        ordering = ["created_at"]


class CustomRuleDefinition(models.Model):
    """
    FR-9: User-defined audit rule with configurable condition logic.
    Rules are scoped to the organization and evaluated against invoices
    during the audit pipeline.
    """

    class Standard(models.TextChoices):
        ZATCA = "zatca", "ZATCA E-Invoicing"
        KPMG = "kpmg", "KPMG"
        DELOITTE = "deloitte", "Deloitte"
        PWC = "pwc", "PwC"
        EY = "ey", "EY"
        CUSTOM = "custom", "Custom"

    class Severity(models.TextChoices):
        CRITICAL = "critical", "Critical"
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    class ConditionType(models.TextChoices):
        MISSING_FIELD = "missing_field", "Field must not be empty"
        AMOUNT_THRESHOLD = "amount_threshold", "Amount above/below threshold"
        DATE_CHECK = "date_check", "Invoice date validation"
        DUPLICATE_CHECK = "duplicate_check", "Duplicate invoice number"
        PATTERN_MATCH = "pattern_match", "Field matches regex pattern"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="custom_rules"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    standard = models.CharField(max_length=20, choices=Standard.choices, default=Standard.CUSTOM)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    condition_type = models.CharField(max_length=30, choices=ConditionType.choices)
    condition_params = models.JSONField(
        default=dict,
        help_text=(
            "Parameters for the condition. Examples:\n"
            "  missing_field:    {\"field\": \"supplier_name\"}\n"
            "  amount_threshold: {\"max_amount\": 500000, \"min_amount\": 0}\n"
            "  date_check:       {\"no_future_dates\": true, \"max_days_old\": 365}\n"
            "  duplicate_check:  {}\n"
            "  pattern_match:    {\"field\": \"invoice_number\", \"pattern\": \"^INV-\\\\d+$\", \"must_match\": true}"
        ),
    )
    remediation_suggestion = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="created_rules")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "custom_rule_definitions"
        ordering = ["name"]
        unique_together = [("organization", "name")]

    def __str__(self):
        return f"[{self.standard.upper()}] {self.name} (v{self.version})"

    def save(self, *args, **kwargs):
        if self.pk:
            # Auto-increment version on update
            CustomRuleDefinition.objects.filter(pk=self.pk).update(version=models.F("version") + 1)
            self.version = CustomRuleDefinition.objects.get(pk=self.pk).version
        super().save(*args, **kwargs)

    def evaluate(self, invoice: dict) -> dict:
        """
        Evaluate this custom rule against an invoice dict.
        Returns {"passed": bool, "explanation": str}
        """
        import re
        ct = self.condition_type
        params = self.condition_params or {}

        try:
            if ct == self.ConditionType.MISSING_FIELD:
                field = params.get("field", "")
                value = invoice.get(field)
                passed = bool(value and str(value).strip())
                return {"passed": passed, "explanation": "" if passed else f"شرط '{field}' مفقود أو فارغ."}

            elif ct == self.ConditionType.AMOUNT_THRESHOLD:
                amount = float(invoice.get("total_amount") or invoice.get("amount") or 0)
                min_a = float(params.get("min_amount", 0))
                max_a = float(params.get("max_amount", float("inf")))
                passed = min_a <= amount <= max_a
                return {"passed": passed, "explanation": "" if passed else f"المبلغ {amount} خارج النطاق المسموح [{min_a} – {max_a}]."}

            elif ct == self.ConditionType.DATE_CHECK:
                from datetime import date
                raw = invoice.get("invoice_date") or invoice.get("date")
                if not raw:
                    return {"passed": False, "explanation": "تاريخ الفاتورة مفقود."}
                inv_date = raw if isinstance(raw, date) else date.fromisoformat(str(raw)[:10])
                today = date.today()
                if params.get("no_future_dates") and inv_date > today:
                    return {"passed": False, "explanation": f"تاريخ الفاتورة {inv_date} في المستقبل."}
                max_days = params.get("max_days_old")
                if max_days and (today - inv_date).days > int(max_days):
                    return {"passed": False, "explanation": f"تاريخ الفاتورة {inv_date} أقدم من {max_days} يوم."}
                return {"passed": True, "explanation": ""}

            elif ct == self.ConditionType.DUPLICATE_CHECK:
                from apps.invoices.models import Invoice as InvoiceModel
                inv_number = invoice.get("invoice_number", "")
                if not inv_number:
                    return {"passed": True, "explanation": ""}
                exists = InvoiceModel.objects.filter(
                    organization_id=self.organization_id, invoice_number=inv_number
                ).count() > 1
                return {"passed": not exists, "explanation": "" if not exists else f"رقم الفاتورة '{inv_number}' مكرر."}

            elif ct == self.ConditionType.PATTERN_MATCH:
                field = params.get("field", "invoice_number")
                pattern = params.get("pattern", "")
                must_match = params.get("must_match", True)
                value = str(invoice.get(field, "") or "")
                matched = bool(re.search(pattern, value)) if pattern else True
                passed = matched if must_match else not matched
                return {"passed": passed, "explanation": "" if passed else f"'{field}' لا يطابق النمط المطلوب: {pattern}"}

        except Exception as e:
            return {"passed": False, "explanation": f"خطأ في تقييم القاعدة: {e}"}

        return {"passed": True, "explanation": ""}
