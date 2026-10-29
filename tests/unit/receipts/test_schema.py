import pytest

from receipts.schema import ExtractedCharge, ExtractedItem, ExtractedReceipt, is_supported_currency
from splitting.money import to_minor


class TestExtractedReceipt:
    def test_basic_parsing(self):
        r = ExtractedReceipt(
            items=[ExtractedItem(description="Nasi Lemak", amount="12.50")],
            charges=[ExtractedCharge(kind="tax", label="SST", amount="0.75")],
            printed_total="13.25",
            currency="MYR",
            title="Test Shop",
        )
        assert len(r.items) == 1
        assert r.items[0].quantity == 1

    def test_decimal_to_minor(self):
        assert to_minor("12.50", "MYR") == 1250
        assert to_minor("100", "JPY") == 100

    def test_excess_precision_rejected(self):
        with pytest.raises(ValueError, match="Excess precision"):
            to_minor("12.501", "MYR")


class TestCurrencySupport:
    def test_supported(self):
        assert is_supported_currency("MYR") is True
        assert is_supported_currency("JPY") is True

    def test_unsupported_flagged(self):
        assert is_supported_currency("XYZ") is False
        assert is_supported_currency("BTC") is False

    def test_case_insensitive(self):
        assert is_supported_currency("myr") is True
