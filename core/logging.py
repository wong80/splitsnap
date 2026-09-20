from __future__ import annotations

import logging
import re

TOKEN_PATTERN = re.compile(r"(?<=/[bs]/)[A-Za-z0-9_-]{32,86}(?=/)")


class TokenRedactionFilter(logging.Filter):
    def filter(self, record):
        if hasattr(record, "msg") and isinstance(record.msg, str):
            record.msg = TOKEN_PATTERN.sub(
                lambda m: m.group()[:8] + "...",
                record.msg,
            )
        return True
