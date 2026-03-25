from dataclasses import dataclass

from apps.rule_engine.rules.gaap.categories.anomaly import GAAPAnomalyPatternRule
from apps.rule_engine.rules.gaap.categories.classification import GAAPClassificationCapexOpexRule
from apps.rule_engine.rules.gaap.categories.completeness import GAAPCompletenessCoreFieldsRule
from apps.rule_engine.rules.gaap.categories.consistency import GAAPConsistencyTreatmentRule
from apps.rule_engine.rules.gaap.categories.cutoff import GAAPCutoffPeriodRule
from apps.rule_engine.rules.gaap.categories.documentation import GAAPDocumentationSupportRule
from apps.rule_engine.rules.gaap.categories.recognition import (
    GAAPExpenseMatchingRule,
    GAAPRevenueRecognitionRule,
)


@dataclass(frozen=True)
class GAAPRuleDefinition:
    rule_code: str
    title: str
    description: str
    category: str
    severity: str
    enabled: bool
    applies_to: tuple[str, ...]
    gaap_principle: str
    weight: float
    rule_class: type


RULE_DEFINITIONS: tuple[GAAPRuleDefinition, ...] = (
    GAAPRuleDefinition(
        rule_code="GAAP-COMP-001",
        title="Core Completeness Fields",
        description="Ensure mandatory accounting fields exist for transaction-level records.",
        category="completeness",
        severity="high",
        enabled=True,
        applies_to=("sales_invoice", "purchase_order", "expense", "bank_statement", "other"),
        gaap_principle="Full Disclosure",
        weight=1.0,
        rule_class=GAAPCompletenessCoreFieldsRule,
    ),
    GAAPRuleDefinition(
        rule_code="GAAP-CUT-001",
        title="Cutoff and Accounting Period",
        description="Ensure posting date and document date are inside the approved accounting period.",
        category="cutoff",
        severity="high",
        enabled=True,
        applies_to=("sales_invoice", "purchase_order", "expense", "tax_return", "other"),
        gaap_principle="Cutoff",
        weight=1.2,
        rule_class=GAAPCutoffPeriodRule,
    ),
    GAAPRuleDefinition(
        rule_code="GAAP-DOC-001",
        title="Supporting Documentation",
        description="Transactions above threshold must include valid supporting evidence.",
        category="documentation",
        severity="high",
        enabled=True,
        applies_to=("sales_invoice", "purchase_order", "expense", "fixed_asset", "other"),
        gaap_principle="Verifiability",
        weight=1.1,
        rule_class=GAAPDocumentationSupportRule,
    ),
    GAAPRuleDefinition(
        rule_code="GAAP-CLS-001",
        title="CAPEX vs OPEX Classification",
        description="Detect likely misclassification of capital expenditures as operating expenses.",
        category="classification",
        severity="medium",
        enabled=True,
        applies_to=("expense", "purchase_order", "fixed_asset", "sales_invoice", "other"),
        gaap_principle="Classification",
        weight=1.0,
        rule_class=GAAPClassificationCapexOpexRule,
    ),
    GAAPRuleDefinition(
        rule_code="GAAP-REV-001",
        title="Revenue Recognition Timing",
        description="Revenue should not be recognized before the supporting performance event.",
        category="recognition",
        severity="high",
        enabled=True,
        applies_to=("sales_invoice", "sales_receipt", "other"),
        gaap_principle="Revenue Recognition",
        weight=1.3,
        rule_class=GAAPRevenueRecognitionRule,
    ),
    GAAPRuleDefinition(
        rule_code="GAAP-EXP-001",
        title="Expense Matching",
        description="Expense recognition should align with related period and activity.",
        category="recognition",
        severity="medium",
        enabled=True,
        applies_to=("expense", "purchase_order", "sales_invoice", "other"),
        gaap_principle="Matching Principle",
        weight=1.0,
        rule_class=GAAPExpenseMatchingRule,
    ),
    GAAPRuleDefinition(
        rule_code="GAAP-CONS-001",
        title="Accounting Treatment Consistency",
        description="Similar transactions should be classified and posted consistently.",
        category="consistency",
        severity="medium",
        enabled=True,
        applies_to=("sales_invoice", "purchase_order", "expense", "bank_statement", "other"),
        gaap_principle="Consistency",
        weight=0.9,
        rule_class=GAAPConsistencyTreatmentRule,
    ),
    GAAPRuleDefinition(
        rule_code="GAAP-ANO-001",
        title="Materiality and Anomaly Pattern",
        description="Flag unusually large, duplicate-like, or suspicious rounded transactions.",
        category="anomaly",
        severity="high",
        enabled=True,
        applies_to=("sales_invoice", "purchase_order", "expense", "bank_statement", "sales_receipt", "other"),
        gaap_principle="Materiality",
        weight=1.2,
        rule_class=GAAPAnomalyPatternRule,
    ),
)


def get_rule_definitions(enabled_only: bool = True) -> list[GAAPRuleDefinition]:
    if enabled_only:
        return [d for d in RULE_DEFINITIONS if d.enabled]
    return list(RULE_DEFINITIONS)


def get_definition_map() -> dict[str, GAAPRuleDefinition]:
    return {d.rule_code: d for d in RULE_DEFINITIONS}
