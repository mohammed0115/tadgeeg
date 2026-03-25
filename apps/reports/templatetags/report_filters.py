from django import template

register = template.Library()


@register.filter
def replace(value, arg):
    """
    Replace occurrences of arg in value with a space.
    Usage: {{ some_key|replace:"_" }}  →  "some key"
    """
    return str(value).replace(str(arg), " ")
