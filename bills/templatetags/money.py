from django import template

from splitting.money import to_display

register = template.Library()


@register.filter
def money(minor: int, currency: str) -> str:
    """Format a minor-unit amount for display, e.g. {{ item.amount_minor|money:bill.currency }}."""
    return to_display(minor, currency)
