from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand, CommandError

from core.probe import run_probe


class Command(BaseCommand):
    help = "Run the synthetic end-to-end journey probe against a running SplitSnap."

    def add_arguments(self, parser):
        parser.add_argument("--base-url", default="http://localhost:8000")
        parser.add_argument(
            "--interval",
            type=float,
            default=0,
            help="Repeat every N seconds forever (0 = run once, exit non-zero on failure).",
        )
        parser.add_argument("--timeout", type=float, default=120.0)

    def handle(self, *args, base_url, interval, timeout, **options):
        while True:
            result = run_probe(base_url, timeout=timeout)
            self.stdout.write(
                json.dumps(
                    {
                        "event": "probe.journey",
                        "ok": result.ok,
                        "step": result.step,
                        "duration_s": round(result.duration_s, 3),
                        "detail": result.detail,
                    }
                )
            )
            if not interval:
                if not result.ok:
                    raise CommandError(f"journey probe failed at {result.step}: {result.detail}")
                return
            time.sleep(interval)
