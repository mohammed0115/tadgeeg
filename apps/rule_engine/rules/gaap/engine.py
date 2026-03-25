from collections import Counter

from apps.rule_engine.rules.base import NormalizedDocument
from apps.rule_engine.rules.gaap.registry import get_rule_definitions
from apps.rule_engine.rules.gaap.result import GAAPRuleResult


class GAAPRuleEngine:
    """Standalone GAAP evaluator for structured, report-ready findings."""

    def __init__(self, definitions=None):
        self.definitions = definitions or get_rule_definitions(enabled_only=True)

    def evaluate(
        self,
        document: NormalizedDocument,
        context: dict | None = None,
        rule_codes: set[str] | None = None,
    ) -> list[GAAPRuleResult]:
        context = context or {}
        results: list[GAAPRuleResult] = []

        for definition in self.definitions:
            if rule_codes and definition.rule_code not in rule_codes:
                continue
            if definition.applies_to and document.document_type not in definition.applies_to:
                continue

            rule_instance = definition.rule_class(config=context.get("rule_config", {}))
            if not rule_instance.check_preconditions(document):
                results.append(
                    GAAPRuleResult(
                        rule_code=definition.rule_code,
                        title=definition.title,
                        status="not_applicable",
                        severity=definition.severity,
                        observation="Rule preconditions were not met for this document.",
                        score_impact=0.0,
                        metadata_json={"document_type": document.document_type},
                    )
                )
                continue

            rule_result = rule_instance.evaluate(rule_instance._build_record(document), context)
            results.append(rule_result)

        return results

    @staticmethod
    def build_summary(results: list[GAAPRuleResult]) -> dict:
        counts = Counter(r.status for r in results)
        total_impact = sum(float(r.score_impact or 0.0) for r in results)
        max_impact = max(len(results), 1)
        gaap_score = max(0.0, round(100.0 - (total_impact / max_impact) * 100.0, 2))
        return {
            "total_rules": len(results),
            "passed": counts.get("passed", 0),
            "failed": counts.get("failed", 0),
            "warning": counts.get("warning", 0),
            "not_applicable": counts.get("not_applicable", 0),
            "total_score_impact": round(total_impact, 2),
            "gaap_score": gaap_score,
        }
