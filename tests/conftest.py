from pathlib import Path
from types import SimpleNamespace

import pytest
from opentelemetry.sdk._logs.export import InMemoryLogExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_TESTS = Path(__file__).parent

# Telemetry is configured once for the whole session with in-memory exporters, exactly
# like production but without a collector. Tests read what would have been exported.
_SPANS = InMemorySpanExporter()
_METRICS = InMemoryMetricReader()
_LOGS = InMemoryLogExporter()


def pytest_collection_modifyitems(items):
    """Mark tests by level from their directory, so `-m unit` / `-m integration` work."""
    for item in items:
        path = Path(item.fspath)
        if _TESTS / "unit" in path.parents:
            item.add_marker(pytest.mark.unit)
        elif _TESTS / "integration" in path.parents:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session", autouse=True)
def _telemetry_session():
    from core import telemetry

    telemetry.setup(span_exporter=_SPANS, metric_reader=_METRICS, log_exporter=_LOGS, batch=False)


@pytest.fixture
def telemetry():
    """Fresh view of exported spans, logs and metrics for one test."""
    _SPANS.clear()
    _LOGS.clear()
    _METRICS.get_metrics_data()  # drain cumulative state read so far

    def metric_points(name):
        data = _METRICS.get_metrics_data()
        points = []
        for rm in data.resource_metrics if data else []:
            for sm in rm.scope_metrics:
                for m in sm.metrics:
                    if m.name == name:
                        points.extend(m.data.data_points)
        return points

    return SimpleNamespace(
        spans=_SPANS.get_finished_spans,
        logs=lambda: [r.log_record for r in _LOGS.get_finished_logs()],
        metric_points=metric_points,
    )
