"""Safe placeholder for catalog rules whose real implementation hasn't shipped yet.

The seed command `seed_document_audit_rules` populates ~236 RuleDefinition rows
from `apps.rule_engine.catalog.document_rules.ALL_RULES`. Until each of those
rules has a real Python class wired up, the seed used to point them all at
`apps.rule_engine.rules.generic.catalog_stub.CatalogStubRule` — but that file
did not exist, so any executor that tried to import the rule blew up.

This module provides a real, importable, safe-by-default class that:

  • Always returns RuleStatus.SKIPPED with explanation = "Not implemented yet".
  • Is NEVER blocking, regardless of catalog severity.
  • Carries `is_blocking = False` and `default_severity = "info"` so a stale
    seed row cannot accidentally fail an audit run or freeze approvals.
  • Records a structured `raw_data["stub_reason"]` so the report layer
    can clearly mark these in the UI as "informational only — no real check".

When a real implementation lands for a given rule_code, update the seed
to point at the new class and re-run `seed_document_audit_rules`.

Discoverability: the management command `validate_rule_catalog` flags any
ACTIVE RuleDefinition still pointing at this stub, so they show up as
work-to-be-done in CI rather than silently passing.
"""
from __future__ import annotations

from typing import Optional

from apps.rule_engine.rules.base import (
    AuditRuleBase,
    NormalizedDocument,
    RuleResult,
    RuleStatus,
)


class CatalogStubRule(AuditRuleBase):
    """Non-blocking placeholder. Always returns SKIPPED."""

    rule_code = "CATALOG-STUB"
    rule_name_en = "Catalog stub — not implemented yet"
    rule_name_ar = "قاعدة كتالوج — لم تُنفَّذ بعد"
    default_severity = "info"  # Lowest. Cannot be blocking.
    rule_type = "validation"
    is_blocking = False

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        # Echo whatever rule_code the seed assigned via config so reports can
        # show the catalog code (e.g. "PI-007") rather than the literal stub
        # marker. This keeps the rule traceable without pretending it ran.
        catalog_code = ""
        if isinstance(self.config, dict):
            catalog_code = (
                self.config.get("catalog_code")
                or self.config.get("rule_code")
                or ""
            )
        category_label = (
            self.config.get("category_label", "") if isinstance(self.config, dict) else ""
        )

        explanation_en = (
            "This catalog rule has no executable implementation yet — "
            "informational only. No audit decision was made."
        )
        explanation_ar = (
            "هذه القاعدة موجودة في الكتالوج فقط وليس لها تنفيذ فعلي بعد — "
            "للعلم فقط، ولم يُتَّخذ أي قرار تدقيق بناءً عليها."
        )

        return RuleResult(
            status=RuleStatus.SKIPPED,
            explanation_en=explanation_en,
            explanation_ar=explanation_ar,
            rule_code=catalog_code or self.rule_code,
            legacy_rule_code=catalog_code or self.rule_code,
            is_blocking=False,
            risk_contribution=0.0,
            evidence=[],
            raw_data={
                "stub_reason": "not_implemented",
                "category_label": category_label,
                "informational_only": True,
            },
        )
