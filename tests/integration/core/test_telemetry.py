"""The receipt journey emits correlated traces, metrics and logs, with no customer data."""

import io

import pytest
from django.test import Client
from PIL import Image

from bills.models import Bill


@pytest.fixture
def demo_extractor(monkeypatch, settings, tmp_path):
    monkeypatch.setenv("RECEIPT_EXTRACTOR", "demo")
    settings.MEDIA_ROOT = tmp_path


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buf, format="PNG")
    buf.seek(0)
    buf.name = "r.png"
    return buf


def _all_text(spans, logs, points):
    """Everything that would leave the process, flattened to strings."""
    out = []
    for s in spans:
        out.append(s.name)
        out.extend(f"{k}={v}" for k, v in (s.attributes or {}).items())
        for e in s.events:
            out.extend(f"{k}={v}" for k, v in (e.attributes or {}).items())
    for r in logs:
        out.append(str(r.body))
        out.extend(f"{k}={v}" for k, v in (r.attributes or {}).items())
    for p in points:
        out.extend(f"{k}={v}" for k, v in (p.attributes or {}).items())
    return "\n".join(out)


@pytest.mark.django_db
def test_upload_journey_is_traced_measured_and_logged(telemetry, demo_extractor):
    client = Client()
    resp = client.post("/", {"receipt": _png()})
    assert resp.status_code == 302

    spans = telemetry.spans()
    names = {s.name for s in spans}
    assert {"receipt.prepare_image", "receipt.extract", "receipt.extract.attempt"} <= names
    assert "bill.persist" in names

    server = next(s for s in spans if s.kind.name == "SERVER" and s.name.startswith("POST"))
    trace_id = server.context.trace_id
    journey = [s for s in spans if s.context.trace_id == trace_id]
    assert {s.name for s in journey} >= {"receipt.extract", "bill.persist"}
    assert resp["X-Trace-ID"] == format(trace_id, "032x")
    assert server.attributes.get("client.address") in (None, "redacted")

    # Structured log for the extraction carries the same trace ID.
    completed = [r for r in telemetry.logs() if r.body == "receipt.extraction.completed"]
    assert completed and completed[-1].trace_id == trace_id
    assert completed[-1].attributes["outcome"] == "match"

    # Metrics: outcome counter and latency histogram.
    counts = telemetry.metric_points("splitsnap.extraction")
    assert any(p.attributes.get("outcome") == "match" and p.value >= 1 for p in counts)
    assert telemetry.metric_points("splitsnap.extraction.duration")
    http = telemetry.metric_points("http.server.request.duration")
    assert http and all("url.path" not in p.attributes for p in http)


@pytest.mark.django_db
def test_no_tokens_or_receipt_contents_leave_the_process(telemetry, demo_extractor):
    organizer = Client()
    admin_url = organizer.post("/", {"receipt": _png()})["Location"]
    bill = Bill.objects.get()
    organizer.post(admin_url, {"action": "confirm"})
    organizer.post(admin_url, {"action": "add_participant", "name": "Zarina Secretname"})
    friend = Client()
    friend.post(f"/s/{bill.share_token}/", {"action": "identify", "name": "Kumar Hiddenname"})
    friend.get(f"/s/{bill.share_token}/")
    organizer.get(f"/b/{bill.admin_token}/nonexistent-404/")

    text = _all_text(
        telemetry.spans(),
        telemetry.logs(),
        telemetry.metric_points("http.server.request.duration"),
    )
    assert text  # something was exported
    for secret in (
        bill.admin_token,
        bill.share_token,
        "Zarina",
        "Kumar",
        "Nasi Lemak",
        "Teh Tarik",
        "Roti Canai",
    ):
        assert secret not in text, f"{secret!r} leaked into telemetry"
