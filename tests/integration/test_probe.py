import pytest

from core.probe import run_probe


@pytest.fixture
def demo_extractor(monkeypatch, settings, tmp_path):
    monkeypatch.setenv("RECEIPT_EXTRACTOR", "demo")
    settings.MEDIA_ROOT = tmp_path


@pytest.mark.django_db(transaction=True)
def test_probe_completes_journey_against_live_server(live_server, demo_extractor):
    result = run_probe(live_server.url, timeout=30)
    assert result.ok, result.detail
    assert result.steps[-1] == "summary"


def test_probe_reports_connection_failure():
    result = run_probe("http://127.0.0.1:9", timeout=2)
    assert not result.ok
    assert result.step == "healthz"
