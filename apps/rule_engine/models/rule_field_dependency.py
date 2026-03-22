"""
RuleFieldDependency — formal contract between rules and canonical fields.
"""
from __future__ import annotations
import uuid
from django.db import models


class RuleFieldDependency(models.Model):
    """
    Declares which canonical fields each rule requires.
    Eliminates silent rule failures caused by missing fields.
    """
    class DependencyType(models.TextChoices):
        REQUIRED       = "required",   "Required — rule returns NOT_APPLICABLE if absent"
        OPTIONAL       = "optional",   "Optional — rule degrades gracefully"
        SUPPORTING     = "supporting", "Supporting — used for evidence/context only"
        CROSS_DOCUMENT = "cross_doc",  "Cross-Document — needs a linked document"

    class NullBehavior(models.TextChoices):
        NOT_APPLICABLE = "not_applicable", "Return NOT_APPLICABLE"
        FAIL           = "fail",           "Fail the rule"
        WARNING        = "warning",        "Return WARNING"
        SKIP           = "skip",           "Skip this sub-check only"

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule_definition = models.ForeignKey(
        "rule_engine.RuleDefinition", on_delete=models.CASCADE,
        related_name="field_dependencies"
    )
    canonical_field_code = models.CharField(
        max_length=100, db_index=True,
        help_text="References CanonicalFieldDefinition.field_code"
    )
    dependency_type = models.CharField(max_length=20, choices=DependencyType.choices, default=DependencyType.REQUIRED)
    null_behavior   = models.CharField(max_length=20, choices=NullBehavior.choices, default=NullBehavior.NOT_APPLICABLE)

    null_message_en = models.CharField(max_length=500, blank=True)
    null_message_ar = models.CharField(max_length=500, blank=True)

    # For cross-document dependencies
    linked_document_type = models.CharField(max_length=50, blank=True)

    class Meta:
        app_label = "rule_engine"
        unique_together = [("rule_definition", "canonical_field_code")]
        verbose_name = "Rule Field Dependency"
        verbose_name_plural = "Rule Field Dependencies"

    def __str__(self):
        return f"{self.rule_definition.rule_code} → {self.canonical_field_code} ({self.dependency_type})"
