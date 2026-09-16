from __future__ import annotations

from pydantic import BaseModel, Field

from splitting.money import CURRENCIES


class ExtractedItem(BaseModel):
    description: str
    quantity: int = 1
    amount: str
    item_discount: str = "0"


class ExtractedCharge(BaseModel):
    kind: str
    label: str = ""
    amount: str


class ExtractedReceipt(BaseModel):
    items: list[ExtractedItem] = Field(default_factory=list)
    charges: list[ExtractedCharge] = Field(default_factory=list)
    printed_total: str = "0"
    currency: str = "MYR"
    title: str = ""


def is_supported_currency(code: str) -> bool:
    return code.upper() in CURRENCIES
