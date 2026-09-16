from __future__ import annotations

import logging
import re

TOKEN_PATTERN = re.compile(r"[0-9a-f]{16,64}")


class TokenRedactionFilter(logging.Filter):
    def filter(self, record):
        if hasattr(record, "msg") and isinstance(record.msg, str):
            record.msg = TOKEN_PATTERN.sub(
                lambda m: m.group()[:8] + "..." if len(m.group()) >= 32 else m.group(),
                record.msg,
            )
        return True
