from receipts.extraction import DemoExtractor
from receipts.validation import run_extraction


class BrokenExtractor:
    def extract(self, image, feedback=None):
        raise TimeoutError("model call timed out")


def _outcomes(telemetry):
    return {
        p.attributes["outcome"]: p.value
        for p in telemetry.metric_points("splitsnap.extraction")
        if p.value
    }


def test_failed_extraction_is_counted_as_error_not_match(telemetry):
    result = run_extraction(b"img", BrokenExtractor())
    assert result.attempts == 2
    assert _outcomes(telemetry).get("error", 0) >= 1

    attempts = [s for s in telemetry.spans() if s.name == "receipt.extract.attempt"]
    assert len(attempts) == 2
    assert all(s.status.status_code.name == "ERROR" for s in attempts)
    assert all(s.events and s.events[0].name == "exception" for s in attempts)


def test_successful_extraction_records_latency(telemetry):
    run_extraction(b"img", DemoExtractor())
    assert _outcomes(telemetry).get("match", 0) >= 1
    hist = telemetry.metric_points("splitsnap.extraction.duration")
    assert any(p.count >= 1 for p in hist)
