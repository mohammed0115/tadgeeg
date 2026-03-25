from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory


class AccountingRuleRegistry:
    _rules: list[type[AccountingRule]] = []
    _loaded = False

    @classmethod
    def register(cls, rule_class: type[AccountingRule]) -> type[AccountingRule]:
        if rule_class not in cls._rules:
            cls._rules.append(rule_class)
        return rule_class

    @classmethod
    def ensure_loaded(cls):
        if cls._loaded:
            return
        from apps.auditing.accounting_rules import standards  # noqa: F401

        cls._loaded = True

    @classmethod
    def get_rules(
        cls,
        standard: AccountingStandard | None = None,
        category: RuleCategory | None = None,
        applies_to: EntityType | None = None,
        enabled_only: bool = True,
    ) -> list[type[AccountingRule]]:
        cls.ensure_loaded()
        rules: list[type[AccountingRule]] = list(cls._rules)

        if standard:
            rules = [rule for rule in rules if rule.standard == standard]
        if category:
            rules = [rule for rule in rules if rule.category == category]
        if applies_to:
            rules = [rule for rule in rules if (not rule.applies_to) or (applies_to in rule.applies_to)]
        if enabled_only:
            rules = [rule for rule in rules if rule.enabled_by_default]

        return sorted(rules, key=lambda r: r.code)
