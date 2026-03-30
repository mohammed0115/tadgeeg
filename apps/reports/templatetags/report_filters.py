from django import template

register = template.Library()


@register.filter
def replace(value, arg):
    """
    Replace occurrences of arg in value with a space.
    Usage: {{ some_key|replace:"_" }}  →  "some key"
    """
    return str(value).replace(str(arg), " ")


def _normalized_status(value):
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "ممتثل": "compliant",
        "متوافق": "compliant",
        "compliant": "compliant",
        "passed": "compliant",
        "ok": "compliant",
        "safe": "compliant",
        "مخالف": "violated",
        "failed": "violated",
        "fail": "violated",
        "violated": "violated",
        "high_risk": "high_risk",
        "critical": "high_risk",
        "high": "high_risk",
        "عالي_المخاطر": "high_risk",
        "عالي": "high_risk",
        "needs_review": "review",
        "review": "review",
        "medium": "review",
        "يحتاج_مراجعة": "review",
    }
    return mapping.get(raw, raw)


@register.filter
def status_key(value):
    return _normalized_status(value)


@register.filter
def is_compliant_status(value):
    return _normalized_status(value) == "compliant"


@register.filter
def is_high_risk_status(value):
    return _normalized_status(value) == "high_risk"


@register.filter
def is_review_status(value):
    return _normalized_status(value) == "review"
