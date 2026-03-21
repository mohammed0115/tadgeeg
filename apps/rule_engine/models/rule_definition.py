import uuid

from django.db import models


class RuleCategory(models.TextChoices):
    DATA_INTEGRITY = "data_integrity", "Data Integrity"
    FINANCIAL_LOGIC = "financial_logic", "Financial Logic"
    COMPLIANCE = "compliance", "Compliance"
    ANOMALY = "anomaly", "Anomaly"
    RISK = "risk", "Risk"
    RECONCILIATION = "reconciliation", "Reconciliation"


class RuleType(models.TextChoices):
    VALIDATION = "validation", "Validation"
    COMPLIANCE = "compliance", "Compliance"
    ANOMALY = "anomaly", "Anomaly"
    RECONCILIATION = "reconciliation", "Reconciliation"
    RISK = "risk", "Risk"


class Severity(models.TextChoices):
    CRITICAL = "critical", "Critical"
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"
    INFO = "info", "Info"


class RuleScope(models.TextChoices):
    GENERIC = "generic", "Generic"
    SPECIALIZED = "specialized", "Specialized"
    CROSS_DOCUMENT = "cross_document", "Cross Document"


class RuleDefinition(models.Model):
    """
    Canonical definition of an audit rule. One record per rule code / version.

    Instances are created by system migrations (is_system_rule=True) or by
    superusers who want to register custom rules.  Runtime behaviour is
    controlled by RuleAssignment, which binds a rule to a document type and
    optionally to a specific organisation.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule_code = models.CharField(max_length=32, unique=True, db_index=True)
    version = models.PositiveSmallIntegerField(default=1)

    # Classification
    category = models.CharField(max_length=32, choices=RuleCategory.choices)
    rule_type = models.CharField(max_length=32, choices=RuleType.choices)
    scope = models.CharField(max_length=32, choices=RuleScope.choices)
    default_severity = models.CharField(
        max_length=16,
        choices=Severity.choices,
        default=Severity.MEDIUM,
    )

    # Implementation
    implementation_class = models.CharField(
        max_length=256,
        help_text=(
            "Dotted Python import path to the class that implements this rule, "
            "e.g. 'apps.rule_engine.rules.generic.missing_fields.MissingFieldsRule'."
        ),
    )
    default_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Default JSON configuration passed to the rule at runtime.",
    )

    # Execution flags
    blocks_approval = models.BooleanField(
        default=False,
        help_text="When True a failure on this rule prevents document approval.",
    )
    requires_cross_document = models.BooleanField(
        default=False,
        help_text="Rule needs data from more than one document.",
    )
    requires_external_reference = models.BooleanField(
        default=False,
        help_text="Rule queries an external data source (e.g. VAT registry).",
    )
    requires_historical_comparison = models.BooleanField(
        default=False,
        help_text="Rule compares against historical records for the same entity.",
    )
    is_ai_rule = models.BooleanField(
        default=False,
        help_text="Rule delegates to an AI/ML model for evaluation.",
    )

    # Lifecycle
    is_active = models.BooleanField(default=True, db_index=True)
    is_system_rule = models.BooleanField(
        default=True,
        help_text="System rules ship with the platform and cannot be deleted.",
    )
    effective_from = models.DateField(null=True, blank=True)
    effective_until = models.DateField(null=True, blank=True)
    deprecated_at = models.DateTimeField(null=True, blank=True)
    deprecation_reason = models.TextField(blank=True)

    # Discoverability
    tags = models.JSONField(default=list, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "re_rule_definition"
        indexes = [
            models.Index(fields=["category", "is_active"], name="re_ruledef_cat_active_idx"),
            models.Index(fields=["rule_type", "scope"], name="re_ruledef_type_scope_idx"),
        ]
        verbose_name = "Rule Definition"
        verbose_name_plural = "Rule Definitions"

    def __str__(self) -> str:
        return f"{self.rule_code} v{self.version}"


class RuleDefinitionTranslation(models.Model):
    """
    Human-readable strings for a RuleDefinition in a specific language.

    Supported language codes: 'en', 'ar'.
    """

    rule = models.ForeignKey(
        RuleDefinition,
        on_delete=models.CASCADE,
        related_name="translations",
    )
    language = models.CharField(
        max_length=8,
        db_index=True,
        help_text="BCP-47 language tag, e.g. 'en' or 'ar'.",
    )
    name = models.CharField(max_length=256)
    description = models.TextField()
    fail_message = models.TextField(
        help_text="Template string shown when this rule fails. May contain {field} placeholders.",
    )
    pass_message = models.TextField(
        blank=True,
        help_text="Template string shown when this rule passes (optional).",
    )
    suggested_action = models.TextField(
        blank=True,
        help_text="Guidance for the reviewer when the rule fails.",
    )

    class Meta:
        db_table = "re_rule_definition_translation"
        unique_together = (("rule", "language"),)
        verbose_name = "Rule Definition Translation"
        verbose_name_plural = "Rule Definition Translations"

    def __str__(self) -> str:
        return f"{self.rule.rule_code} [{self.language}]"
