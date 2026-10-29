"""OpenTelemetry bootstrap: traces, metrics and logs that share one trace ID.

``configure_from_env()`` is called from ``config/wsgi.py`` in every gunicorn worker. It does
nothing unless ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, so tests, ``runserver`` and CI run
without a collector. Tests call ``setup()`` with in-memory exporters instead.

Privacy: admin/share tokens are scrubbed from URL attributes before a span ends, HTTP
metrics use the route template (``b/<str:admin_token>/``) rather than the path, and the
token redaction filter runs on the log handler that exports to OTLP. Receipt contents and
participant names are never set as attributes (see AGENTS.md guardrail 3).
"""

from __future__ import annotations

import logging
import os
import re

from opentelemetry import _logs, metrics, trace
from opentelemetry.sdk.resources import Resource

from core.logging import TokenRedactionFilter

_TOKEN_IN_PATH = re.compile(r"(/[bs]/)[A-Za-z0-9_-]{16,86}(/)")
_URL_ATTRIBUTES = ("url.path", "url.full", "http.target", "http.url")
# Client IPs are personal data; the route, status and timing are enough to debug.
_PERSONAL_ATTRIBUTES = ("client.address", "net.peer.ip", "http.client_ip")

_configured = False

tracer = trace.get_tracer("splitsnap")
meter = metrics.get_meter("splitsnap")

# --- Instruments for the receipt journey (no-ops until a provider is configured) ---
extraction_duration = meter.create_histogram(
    "splitsnap.extraction.duration",
    unit="s",
    description="End-to-end receipt extraction time including the retry",
    explicit_bucket_boundaries_advisory=[0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 45, 60, 90],
)
extraction_counter = meter.create_counter(
    "splitsnap.extraction",
    description="Receipt extractions by outcome (match, mismatch, unsupported_currency, error)",
)
bills_locked_counter = meter.create_counter(
    "splitsnap.bills.locked", description="Bills locked (settlement computed)"
)


def scrub_tokens(value: str) -> str:
    """Replace the 256-bit admin/share token in a URL or path with a fixed marker."""
    return _TOKEN_IN_PATH.sub(r"\1{token}\2", value)


def _response_hook(span, request, response) -> None:
    if not span or not span.is_recording():
        return
    for key in _URL_ATTRIBUTES:
        value = span.attributes.get(key) if span.attributes else None
        if isinstance(value, str):
            span.set_attribute(key, scrub_tokens(value))
    for key in _PERSONAL_ATTRIBUTES:
        if span.attributes and key in span.attributes:
            span.set_attribute(key, "redacted")


def _resource() -> Resource:
    return Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME", "splitsnap"),
            "service.version": os.environ.get("SERVICE_VERSION", "dev"),
            "deployment.environment.name": os.environ.get("DEPLOY_ENV", "local"),
        }
    )


def setup(*, span_exporter, metric_reader, log_exporter=None, batch: bool = True) -> None:
    """Install global providers and instrument Django and psycopg. Idempotent.

    The Anthropic SDK's HTTP client is not auto-instrumented; each model call is covered by
    the ``receipt.extract.attempt`` span in ``receipts.validation``.
    """
    global _configured
    if _configured:
        return
    _configured = True

    # Stable HTTP semantic conventions: metrics carry http.route, never the raw path.
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    os.environ.setdefault("OTEL_PYTHON_DJANGO_EXCLUDED_URLS", "healthz")

    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, SimpleLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    resource = _resource()

    tracer_provider = TracerProvider(resource=resource)
    span_processor = BatchSpanProcessor if batch else SimpleSpanProcessor
    tracer_provider.add_span_processor(span_processor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))

    if log_exporter is not None:
        logger_provider = LoggerProvider(resource=resource)
        log_processor = BatchLogRecordProcessor if batch else SimpleLogRecordProcessor
        logger_provider.add_log_record_processor(log_processor(log_exporter))
        _logs.set_logger_provider(logger_provider)
        # Under gunicorn, Django's LOGGING (config/settings/prod.py) later installs its own
        # "otlp" handler bound to this provider. Attaching here covers runserver and tests.
        handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
        handler.addFilter(TokenRedactionFilter())
        for name in ("", "bills", "receipts", "core"):
            app_logger = logging.getLogger(name)
            app_logger.addHandler(handler)
            if name and app_logger.level == logging.NOTSET:
                app_logger.setLevel(logging.INFO)  # domain events are INFO

    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor

    DjangoInstrumentor().instrument(response_hook=_response_hook)
    PsycopgInstrumentor().instrument(enable_commenter=False)


def configure_from_env() -> bool:
    """Export over OTLP/HTTP when OTEL_EXPORTER_OTLP_ENDPOINT is set. Returns True if enabled."""
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False

    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    setup(
        span_exporter=OTLPSpanExporter(),
        metric_reader=PeriodicExportingMetricReader(
            OTLPMetricExporter(), export_interval_millis=10_000
        ),
        log_exporter=OTLPLogExporter(),
    )
    return True
