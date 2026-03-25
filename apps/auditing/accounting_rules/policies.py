from copy import deepcopy

from django.conf import settings

from apps.auditing.accounting_rules.enums import AccountingStandard


DEFAULT_POLICIES = {
    AccountingStandard.GAAP.value: {
        "materiality_amount": 10000,
        "max_period_gap_days": 90,
        "max_posting_gap_days": 7,
        "required_fields": ["date", "amount", "account", "counterparty", "reference"],
    },
    AccountingStandard.IFRS.value: {
        "materiality_amount": 12000,
        "max_period_gap_days": 90,
        "max_posting_gap_days": 7,
        "required_fields": ["date", "amount", "account", "counterparty", "reference"],
    },
    "global": {
        "scoring": {
            "passed": 0.0,
            "warning": 0.5,
            "failed": 1.0,
            "not_applicable": 0.0,
            "insufficient_data": 0.0,
        }
    },
}


def get_policy(standard: AccountingStandard, overrides: dict | None = None) -> dict:
    base = deepcopy(DEFAULT_POLICIES.get(standard.value, {}))
    user_defined = getattr(settings, "ACCOUNTING_RULE_POLICIES", {})
    configured = user_defined.get(standard.value, {}) if isinstance(user_defined, dict) else {}
    merged = _deep_merge(base, configured)
    if overrides:
        merged = _deep_merge(merged, overrides)
    return merged


def get_global_policy() -> dict:
    base = deepcopy(DEFAULT_POLICIES["global"])
    user_defined = getattr(settings, "ACCOUNTING_RULE_POLICIES", {})
    configured = user_defined.get("global", {}) if isinstance(user_defined, dict) else {}
    return _deep_merge(base, configured)


def _deep_merge(base: dict, extra: dict) -> dict:
    result = deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
