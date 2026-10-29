from receipts.extraction import DemoExtractor, FakeExtractor, get_extractor
from receipts.validation import compute_gap


def test_demo_receipt_reconciles_to_printed_total():
    receipt = DemoExtractor().extract(b"ignored")
    assert receipt.currency == "MYR"
    assert len(receipt.items) == 3
    assert compute_gap(receipt, receipt.currency) == 0


def test_get_extractor_selects_demo(monkeypatch):
    monkeypatch.setenv("RECEIPT_EXTRACTOR", "demo")
    assert isinstance(get_extractor(), DemoExtractor)


def test_get_extractor_defaults_to_fake(monkeypatch):
    monkeypatch.delenv("RECEIPT_EXTRACTOR", raising=False)
    assert isinstance(get_extractor(), FakeExtractor)
