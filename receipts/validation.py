from __future__ import annotations

import datetime
import logging
import time
from dataclasses import dataclass

from splitting.money import to_minor

from .extraction import ReceiptExtractor
from .schema import ExtractedReceipt, is_supported_currency

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    receipt: ExtractedReceipt
    attempts: int
    gap: int
    status: str
    currency_supported: bool


def compute_gap(receipt: ExtractedReceipt, currency: str) -> int:
    item_total = 0
    for item in receipt.items:
        net = to_minor(item.amount, currency) - to_minor(item.item_discount, currency)
        item_total += net
    charge_total = sum(to_minor(ch.amount, currency) for ch in receipt.charges)
    printed = to_minor(receipt.printed_total, currency)
    return item_total + charge_total - printed


def _log_extraction(result: ExtractionResult, latency_ms: int) -> None:
    outcome = "match" if result.gap == 0 else "mismatch"
    if not result.currency_supported:
        outcome = "unsupported_currency"
    logger.info(
        "receipt.extraction.completed",
        extra={
            "attempts": result.attempts,
            "gap": result.gap,
            "outcome": outcome,
            "latency_ms": latency_ms,
        },
    )


def run_extraction(
    image: bytes,
    extractor: ReceiptExtractor,
) -> ExtractionResult:
    attempts = 0
    receipt: ExtractedReceipt | None = None
    gap = 0
    currency_supported = True
    t0 = time.monotonic()

    for attempt in range(2):
        attempts = attempt + 1
        feedback = None
        if attempt == 1 and receipt is not None and gap != 0:
            feedback = (
                f"The items and charges sum to a different value than the printed total. "
                f"The gap is {gap} minor units. Please re-extract carefully."
            )

        try:
            receipt = extractor.extract(image, feedback=feedback)
        except Exception:
            receipt = None
            continue

        currency = receipt.currency.upper()
        currency_supported = is_supported_currency(currency)

        if not currency_supported:
            result = ExtractionResult(
                receipt=receipt,
                attempts=attempts,
                gap=0,
                status="review",
                currency_supported=False,
            )
            _log_extraction(result, int((time.monotonic() - t0) * 1000))
            return result

        try:
            gap = compute_gap(receipt, currency)
        except (ValueError, KeyError):
            receipt = None
            continue

        if gap == 0:
            if not receipt.title:
                receipt = receipt.model_copy(
                    update={"title": f"Receipt {datetime.date.today().isoformat()}"}
                )
            result = ExtractionResult(
                receipt=receipt,
                attempts=attempts,
                gap=0,
                status="review",
                currency_supported=True,
            )
            _log_extraction(result, int((time.monotonic() - t0) * 1000))
            return result

    if receipt is None:
        receipt = ExtractedReceipt(title=f"Receipt {datetime.date.today().isoformat()}")

    if not receipt.title:
        receipt = receipt.model_copy(
            update={"title": f"Receipt {datetime.date.today().isoformat()}"}
        )

    result = ExtractionResult(
        receipt=receipt,
        attempts=attempts,
        gap=gap,
        status="review",
        currency_supported=currency_supported,
    )
    _log_extraction(result, int((time.monotonic() - t0) * 1000))
    return result
