# DEPRECATED: AccountingRulesEngine is superseded by AuditPipelineV2 + GAAP rules.
# Run: python manage.py seed_gaap_rule_definitions
# to register GAAP rules in the V2 pipeline. This file will be removed in a future release.

from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleStatus
from apps.auditing.accounting_rules.policies import get_global_policy, get_policy
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import EvaluationResult, RuleResult
from apps.auditing.accounting_rules.scoring import RuleScoringEngine


class AccountingRulesEngine:
    def evaluate(
        self,
        record: dict,
        standard: AccountingStandard,
        context: dict | None = None,
        category: RuleCategory | None = None,
    ) -> EvaluationResult:
        context = dict(context or {})
        policy = get_policy(standard, overrides=context.get("policy_override"))
        global_policy = get_global_policy()
        scoring_engine = RuleScoringEngine(global_policy.get("scoring", {}))

        entity_type = EntityType(str(record.get("record_type") or "document"))
        rules = AccountingRuleRegistry.get_rules(
            standard=standard,
            category=category,
            applies_to=entity_type,
            enabled_only=True,
        )

        results: list[RuleResult] = []
        for rule_class in rules:
            rule = rule_class(config=policy)
            if not rule.is_applicable(record, context):
                results.append(
                    RuleResult(
                        rule_code=rule.code,
                        title=rule.title,
                        standard=rule.standard,
                        category=rule.category,
                        status=RuleStatus.NOT_APPLICABLE,
                        severity=rule.severity,
                        observation="Rule not applicable for this record context.",
                    )
                )
                continue

            result = rule.evaluate(record, context)
            if not result.recommendation:
                result.recommendation = rule.get_recommendation(record, context)
            results.append(result)

        summary = scoring_engine.summarize(results)

        return EvaluationResult(
            record_type=str(record.get("record_type") or "document"),
            record_id=str(record.get("record_id") or record.get("id") or ""),
            standard=standard,
            summary=summary,
            results=results,
        )
