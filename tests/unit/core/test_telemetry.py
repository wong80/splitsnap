import logging

from opentelemetry import trace

from core.logging import TokenRedactionFilter, TraceContextFilter
from core.telemetry import scrub_tokens

TOKEN = "Ab3_" + "x" * 39


def test_scrub_tokens_replaces_admin_and_share_tokens():
    assert scrub_tokens(f"/b/{TOKEN}/") == "/b/{token}/"
    assert scrub_tokens(f"https://h/s/{TOKEN}/summary") == "https://h/s/{token}/summary"
    assert scrub_tokens("/healthz") == "/healthz"


def test_trace_context_filter_adds_ids_inside_a_span():
    record = logging.LogRecord("t", logging.INFO, "", 0, "msg", (), None)
    with trace.get_tracer("test").start_as_current_span("unit") as span:
        TraceContextFilter().filter(record)
        expected = format(span.get_span_context().trace_id, "032x")
    assert record.trace_id == expected
    assert len(record.span_id) == 16


def test_trace_context_filter_blank_outside_a_span():
    record = logging.LogRecord("t", logging.INFO, "", 0, "msg", (), None)
    TraceContextFilter().filter(record)
    assert record.trace_id == ""


def test_redaction_applies_to_log_arguments():
    record = logging.LogRecord(
        "django.request",
        logging.ERROR,
        "",
        0,
        "Internal Server Error: %s",
        (f"/b/{TOKEN}/",),
        None,
    )
    TokenRedactionFilter().filter(record)
    assert TOKEN not in record.getMessage()
    assert record.getMessage().startswith("Internal Server Error: /b/Ab3_xxxx...")


def test_redaction_replaces_request_extra_with_safe_summary():
    class FakeRequest:
        method = "POST"
        path = f"/s/{TOKEN}/"

    record = logging.LogRecord("django.request", logging.ERROR, "", 0, "boom", (), None)
    record.request = FakeRequest()
    TokenRedactionFilter().filter(record)
    assert record.request == "POST /s/Ab3_xxxx.../"
