from __future__ import annotations

from decimal import Decimal, InvalidOperation

CURRENCIES: dict[str, int] = {
    "MYR": 2,
    "SGD": 2,
    "USD": 2,
    "THB": 2,
    "EUR": 2,
    "GBP": 2,
    "AUD": 2,
    "CAD": 2,
    "CNY": 2,
    "HKD": 2,
    "TWD": 2,
    "IDR": 2,
    "PHP": 2,
    "VND": 0,
    "JPY": 0,
    "KRW": 0,
}

CURRENCY_SYMBOLS: dict[str, str] = {
    "MYR": "RM",
    "SGD": "S$",
    "USD": "$",
    "THB": "฿",
    "EUR": "€",
    "GBP": "£",
    "AUD": "A$",
    "CAD": "C$",
    "CNY": "¥",
    "HKD": "HK$",
    "TWD": "NT$",
    "IDR": "Rp",
    "PHP": "₱",
    "VND": "₫",
    "JPY": "¥",
    "KRW": "₩",
}


def exponent(currency: str) -> int:
    currency = currency.upper()
    if currency not in CURRENCIES:
        raise ValueError(f"Unsupported currency: {currency}")
    return CURRENCIES[currency]


def to_minor(amount: str | Decimal, currency: str) -> int:
    currency = currency.upper()
    exp = exponent(currency)
    try:
        d = Decimal(amount)
    except InvalidOperation:
        raise ValueError(f"Invalid decimal: {amount!r}") from None
    if not d.is_finite():
        raise ValueError(f"Invalid decimal: {amount!r}")
    scaled = d * Decimal(10**exp)
    if scaled != scaled.to_integral_value():
        raise ValueError(
            f"Excess precision for {currency}: {amount!r} has more than {exp} decimal places"
        )
    return int(scaled)


def to_display(minor: int, currency: str) -> str:
    currency = currency.upper()
    exp = exponent(currency)
    if exp == 0:
        return str(minor)
    whole, frac = divmod(abs(minor), 10**exp)
    sign = "-" if minor < 0 else ""
    return f"{sign}{whole}.{frac:0{exp}d}"


def rescale_minor(minor: int, from_currency: str, to_currency: str) -> int:
    """Re-express a minor-unit amount in another currency's exponent, keeping the same
    displayed number (5000 MYR sen = "50.00" -> 50 JPY = "50").

    No exchange rate is applied: this is for relabelling a Bill's currency during review.
    Raises ValueError if the target currency cannot represent the amount exactly.
    """
    shift = exponent(to_currency) - exponent(from_currency)
    if shift >= 0:
        return minor * 10**shift
    factor = 10**-shift
    if minor % factor:
        raise ValueError(
            f"{to_currency.upper()} cannot represent {to_display(minor, from_currency)} "
            f"{from_currency.upper()} exactly"
        )
    return minor // factor


def symbol(currency: str) -> str:
    currency = currency.upper()
    return CURRENCY_SYMBOLS.get(currency, currency)
