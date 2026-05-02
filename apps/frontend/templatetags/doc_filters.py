"""Template filters for the typed-document list / detail templates."""
from django import template

register = template.Library()


@register.filter(name="get_field")
def get_field(obj, attr):
    """Resolve `obj.attr` (or `obj[attr]`) safely from a template.

    Supports both Django model instances and plain dicts. Returns None when
    the attribute doesn't exist so the template can show "—".
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(attr)
    return getattr(obj, attr, None)
