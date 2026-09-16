from decimal import Decimal

import pytest

from splitting.money import CURRENCIES, exponent, symbol, to_display, to_minor


class TestExponent:
    def test_myr(self):
        assert exponent("MYR") == 2

    def test_jpy(self):
        assert exponent("JPY") == 0

    def test_case_insensitive(self):
        assert exponent("myr") == 2

    def test_unsupported(self):
        with pytest.raises(ValueError, match="Unsupported currency"):
            exponent("XYZ")


class TestToMinor:
    @pytest.mark.parametrize(
        "amount, currency, expected",
        [
            ("10.00", "MYR", 1000),
            ("23.50", "MYR", 2350),
            ("0.01", "USD", 1),
            ("100", "JPY", 100),
            ("0", "MYR", 0),
            ("-5.25", "SGD", -525),
        ],
    )
    def test_conversions(self, amount, currency, expected):
        assert to_minor(amount, currency) == expected

    def test_decimal_input(self):
        assert to_minor(Decimal("10.00"), "MYR") == 1000

    def test_excess_precision_rejected(self):
        with pytest.raises(ValueError, match="Excess precision"):
            to_minor("10.001", "MYR")

    def test_jpy_rejects_fractional(self):
        with pytest.raises(ValueError, match="Excess precision"):
            to_minor("10.5", "JPY")

    def test_invalid_string(self):
        with pytest.raises(ValueError, match="Invalid decimal"):
            to_minor("abc", "MYR")

    def test_infinity_rejected(self):
        with pytest.raises(ValueError, match="Invalid decimal"):
            to_minor("Infinity", "MYR")


class TestToDisplay:
    @pytest.mark.parametrize(
        "minor, currency, expected",
        [
            (2350, "MYR", "23.50"),
            (1, "USD", "0.01"),
            (100, "JPY", "100"),
            (0, "MYR", "0.00"),
            (-525, "SGD", "-5.25"),
        ],
    )
    def test_formatting(self, minor, currency, expected):
        assert to_display(minor, currency) == expected


class TestSymbol:
    def test_known(self):
        assert symbol("MYR") == "RM"
        assert symbol("JPY") == "¥"

    def test_fallback(self):
        assert symbol("myr") == "RM"


class TestCurrencyWhitelist:
    def test_all_exponents_valid(self):
        for code, exp in CURRENCIES.items():
            assert exp in (0, 2), f"{code} has unexpected exponent {exp}"
