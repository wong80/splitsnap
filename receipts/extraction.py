from __future__ import annotations

import base64
import json
import os
from typing import Protocol

from .schema import ExtractedReceipt

PROMPT_VERSION = "extract_v1"


class ReceiptExtractor(Protocol):
    def extract(self, image: bytes, feedback: str | None = None) -> ExtractedReceipt: ...


class AnthropicExtractor:
    def __init__(self) -> None:
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = os.environ.get("RECEIPT_MODEL", "claude-sonnet-4-20250514")

    def extract(self, image: bytes, feedback: str | None = None) -> ExtractedReceipt:
        prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "extract_v1.md")
        with open(prompt_path) as f:
            system_prompt = f.read()

        b64 = base64.standard_b64encode(image).decode("ascii")
        content: list[dict] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            },
            {"type": "text", "text": "Extract the receipt data as JSON."},
        ]
        if feedback:
            content.append({"type": "text", "text": f"Feedback: {feedback}"})

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
            timeout=45.0,
        )

        if not response.content or not hasattr(response.content[0], "text"):
            raise ValueError("Unexpected API response: no text content")

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        data = json.loads(text)
        return ExtractedReceipt.model_validate(data)


class FakeExtractor:
    def __init__(self, fixture: ExtractedReceipt | None = None) -> None:
        self.fixture = fixture
        self.call_count = 0

    def extract(self, image: bytes, feedback: str | None = None) -> ExtractedReceipt:
        self.call_count += 1
        if self.fixture is not None:
            return self.fixture
        return ExtractedReceipt(
            items=[],
            charges=[],
            printed_total="0",
            currency="MYR",
            title="Test Receipt",
        )


def get_extractor() -> ReceiptExtractor:
    backend = os.environ.get("RECEIPT_EXTRACTOR", "fake")
    if backend == "anthropic":
        return AnthropicExtractor()
    return FakeExtractor()
