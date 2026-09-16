from __future__ import annotations

import json
import time
from difflib import SequenceMatcher
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from receipts.extraction import get_extractor
from receipts.images import prepare_image
from receipts.validation import run_extraction


def _fuzzy_match(a: str, b: str) -> bool:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.6


class Command(BaseCommand):
    help = "Evaluate receipt extraction against golden-set fixtures."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            default=str(Path(settings.BASE_DIR) / "evals" / "receipts"),
            help="Directory containing <name>.jpg and <name>.expected.json pairs.",
        )

    def handle(self, *args, **options):
        evals_dir = Path(options["dir"])
        expected_files = sorted(evals_dir.glob("*.expected.json"))

        if not expected_files:
            self.stderr.write("No expected files found.")
            return

        extractor = get_extractor()
        results = []

        for expected_path in expected_files:
            name = expected_path.name.replace(".expected.json", "")
            image_path = None
            for ext in ("jpg", "jpeg", "png", "webp", "heic"):
                candidate = evals_dir / f"{name}.{ext}"
                if candidate.exists():
                    image_path = candidate
                    break

            if not image_path:
                self.stderr.write(f"  SKIP {name}: no image file found")
                continue

            with open(expected_path) as f:
                expected = json.load(f)

            image_data = prepare_image(image_path.read_bytes())

            t0 = time.monotonic()
            result = run_extraction(image_data, extractor)
            latency_ms = int((time.monotonic() - t0) * 1000)

            receipt = result.receipt
            r = {
                "name": name,
                "latency_ms": latency_ms,
                "attempts": result.attempts,
                "gap": result.gap,
                "total_match": receipt.printed_total == expected.get("printed_total"),
                "currency_match": receipt.currency.upper() == expected.get("currency", "").upper(),
                "reconciled": result.gap == 0,
                "item_precision": 0.0,
                "item_recall": 0.0,
            }

            expected_items = expected.get("items", [])
            extracted_items = receipt.items
            matched = 0
            for ei in expected_items:
                for xi in extracted_items:
                    if xi.amount == ei["amount"] or _fuzzy_match(
                        xi.description, ei["description"]
                    ):
                        matched += 1
                        break

            if extracted_items:
                r["item_precision"] = matched / len(extracted_items)
            if expected_items:
                r["item_recall"] = matched / len(expected_items)

            results.append(r)
            self.stdout.write(
                f"  {name}: total={'OK' if r['total_match'] else 'MISS'} "
                f"currency={'OK' if r['currency_match'] else 'MISS'} "
                f"gap={result.gap} attempts={result.attempts} "
                f"latency={latency_ms}ms"
            )

        if not results:
            self.stderr.write("No evaluations completed.")
            return

        n = len(results)
        self.stdout.write(f"\n--- Summary ({n} receipts) ---")
        self.stdout.write(
            f"Printed-total exact match: {sum(r['total_match'] for r in results)}/{n}"
        )
        self.stdout.write(f"Currency accuracy: {sum(r['currency_match'] for r in results)}/{n}")
        self.stdout.write(f"Reconciliation pass rate: {sum(r['reconciled'] for r in results)}/{n}")
        avg_precision = sum(r["item_precision"] for r in results) / n
        avg_recall = sum(r["item_recall"] for r in results) / n
        self.stdout.write(f"Item precision (avg): {avg_precision:.2%}")
        self.stdout.write(f"Item recall (avg): {avg_recall:.2%}")
        avg_attempts = sum(r["attempts"] for r in results) / n
        avg_latency = sum(r["latency_ms"] for r in results) / n
        self.stdout.write(f"Avg attempts: {avg_attempts:.1f}")
        self.stdout.write(f"Avg latency: {avg_latency:.0f}ms")

        md = "## Eval Results\n\n"
        md += "| Receipt | Total | Currency | Gap | P | R | Attempts | Latency |\n"
        md += "|---------|-------|----------|-----|---|---|----------|---------|\n"
        for r in results:
            md += (
                f"| {r['name']} "
                f"| {'OK' if r['total_match'] else 'MISS'} "
                f"| {'OK' if r['currency_match'] else 'MISS'} "
                f"| {r['gap']} "
                f"| {r['item_precision']:.0%} "
                f"| {r['item_recall']:.0%} "
                f"| {r['attempts']} "
                f"| {r['latency_ms']}ms |\n"
            )
        md += f"\n**{n} receipts evaluated.**\n"

        summary_path = Path(options["dir"]) / "eval_summary.md"
        summary_path.write_text(md, encoding="utf-8")
        self.stdout.write(f"\nMarkdown summary written to {summary_path}")
