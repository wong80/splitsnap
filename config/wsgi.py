import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

# Telemetry must be configured before the WSGI handler loads middleware so the
# OpenTelemetry Django middleware is installed. No-op without OTEL_EXPORTER_OTLP_ENDPOINT.
from core.telemetry import configure_from_env  # noqa: E402

configure_from_env()

application = get_wsgi_application()
