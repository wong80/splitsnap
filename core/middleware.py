from __future__ import annotations

import uuid

from opentelemetry import trace


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or _trace_id() or uuid.uuid4().hex[:16]
        request.request_id = request_id
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        if trace_id := _trace_id():
            # Lets a user-reported failure be looked up directly in Tempo.
            response["X-Trace-ID"] = trace_id
        return response


def _trace_id() -> str:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else ""


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Referrer-Policy"] = "same-origin"
        response["X-Robots-Tag"] = "noindex"
        return response
