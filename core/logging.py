from __future__ import annotations

import logging
import re

from opentelemetry import trace

TOKEN_PATTERN = re.compile(r"(?<=/[bs]/)[A-Za-z0-9_-]{32,86}(?=/)")


def _redact(text: str) -> str:
    return TOKEN_PATTERN.sub(lambda m: m.group()[:8] + "...", text)


class TokenRedactionFilter(logging.Filter):
    """Truncate admin/share tokens in log messages, their arguments and request extras."""

    def filter(self, record):
        if isinstance(getattr(record, "msg", None), str):
            if record.args:
                # Django logs request paths as arguments ("Internal Server Error: %s").
                try:
                    record.msg = record.msg % record.args
                    record.args = ()
                except (TypeError, ValueError):
                    pass
            record.msg = _redact(record.msg)
        request = getattr(record, "request", None)
        if request is not None and not isinstance(request, str):
            # Django attaches the HttpRequest; keep only method + redacted path.
            path = getattr(request, "path", "")
            record.request = f"{getattr(request, 'method', '')} {_redact(path)}".strip()
        return True


class TraceContextFilter(logging.Filter):
    """Add the current trace_id/span_id so every log line can be joined to its trace."""

    def filter(self, record):
        ctx = trace.get_current_span().get_span_context()
        if ctx.is_valid:
            record.trace_id = format(ctx.trace_id, "032x")
            record.span_id = format(ctx.span_id, "016x")
        else:
            record.trace_id = ""
            record.span_id = ""
        return True
