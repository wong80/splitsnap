from receipts.extraction import FakeExtractor
from receipts.schema import ExtractedCharge, ExtractedItem, ExtractedReceipt
from receipts.validation import compute_gap, run_extraction


def make_receipt(items=None, charges=None, printed_total="10.00", currency="MYR", title="Shop"):
    return ExtractedReceipt(
        items=items or [ExtractedItem(description="Item", amount="10.00")],
        charges=charges or [],
        printed_total=printed_total,
        currency=currency,
        title=title,
    )


class TestComputeGap:
    def test_zero_gap(self):
        r = make_receipt(printed_total="10.00")
        assert compute_gap(r, "MYR") == 0

    def test_positive_gap(self):
        r = make_receipt(printed_total="9.00")
        assert compute_gap(r, "MYR") == 100

    def test_negative_gap(self):
        r = make_receipt(printed_total="11.00")
        assert compute_gap(r, "MYR") == -100

    def test_with_charges(self):
        r = make_receipt(
            charges=[ExtractedCharge(kind="tax", amount="0.60")],
            printed_total="10.60",
        )
        assert compute_gap(r, "MYR") == 0

    def test_with_discount(self):
        r = make_receipt(
            items=[ExtractedItem(description="X", amount="10.00", item_discount="2.00")],
            printed_total="8.00",
        )
        assert compute_gap(r, "MYR") == 0


class TestRunExtraction:
    def test_match_first_call(self):
        receipt = make_receipt()
        extractor = FakeExtractor(fixture=receipt)
        result = run_extraction(b"img", extractor)
        assert result.attempts == 1
        assert result.gap == 0
        assert extractor.call_count == 1

    def test_mismatch_then_match(self):
        bad = make_receipt(printed_total="9.00")
        good = make_receipt(printed_total="10.00")

        class TwoTryExtractor:
            def __init__(self):
                self.calls = 0

            def extract(self, image, feedback=None):
                self.calls += 1
                if self.calls == 1:
                    return bad
                return good

        extractor = TwoTryExtractor()
        result = run_extraction(b"img", extractor)
        assert result.attempts == 2
        assert result.gap == 0
        assert extractor.calls == 2

    def test_mismatch_twice(self):
        bad = make_receipt(printed_total="9.00")
        extractor = FakeExtractor(fixture=bad)
        result = run_extraction(b"img", extractor)
        assert result.attempts == 2
        assert result.gap != 0
        assert result.status == "review"

    def test_invalid_schema_counts_as_attempt(self):
        class FailingExtractor:
            def __init__(self):
                self.calls = 0

            def extract(self, image, feedback=None):
                self.calls += 1
                raise ValueError("bad json")

        extractor = FailingExtractor()
        result = run_extraction(b"img", extractor)
        assert result.attempts == 2
        assert extractor.calls == 2
        assert result.status == "review"

    def test_never_more_than_two_calls(self):
        class CountExtractor:
            def __init__(self):
                self.calls = 0

            def extract(self, image, feedback=None):
                self.calls += 1
                raise ValueError("always fail")

        extractor = CountExtractor()
        run_extraction(b"img", extractor)
        assert extractor.calls == 2

    def test_unsupported_currency(self):
        receipt = make_receipt(currency="XYZ")
        extractor = FakeExtractor(fixture=receipt)
        result = run_extraction(b"img", extractor)
        assert result.currency_supported is False
        assert result.status == "review"
        assert result.attempts == 1

    def test_both_fail_empty_items(self):
        class AlwaysFail:
            def __init__(self):
                self.calls = 0

            def extract(self, image, feedback=None):
                self.calls += 1
                raise Exception("boom")

        result = run_extraction(b"img", AlwaysFail())
        assert result.receipt.items == []
        assert result.status == "review"

    def test_title_fallback(self):
        receipt = make_receipt(title="")
        extractor = FakeExtractor(fixture=receipt)
        result = run_extraction(b"img", extractor)
        assert "Receipt" in result.receipt.title
