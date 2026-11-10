"""Guards on the provisioned alert rules and dashboard (issue #30).

ReceiptExtractionFailing must page only on real extraction errors. An unsupported currency
is a handled path since #31 (the organizer picks a currency), so counting it would page
on-call while nothing is broken.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ALERTS = ROOT / "observability" / "grafana" / "alerting" / "splitsnap-alerts.yaml"
DASHBOARD = ROOT / "observability" / "grafana" / "dashboards" / "splitsnap.json"


def _rule_block(title: str) -> str:
    text = ALERTS.read_text(encoding="utf-8")
    blocks = re.split(r"\n      - uid: ", text)
    return next(b for b in blocks if f"title: {title}\n" in b)


def test_extraction_alert_counts_only_errors():
    block = _rule_block("ReceiptExtractionFailing")
    query = block.split("annotations:")[0]
    # Numerator: errors only. Denominator: every extraction (no label filter).
    assert re.findall(r"splitsnap_extraction_total\{([^}]*)\}", query) == ['outcome="error"']
    assert "splitsnap_extraction_total[5m]" in query
    assert "unsupported_currency" not in query


def test_every_rule_links_a_runbook_that_exists():
    for title in ("ReceiptExtractionFailing", "HighServerErrorRate"):
        url = re.search(r"runbook_url: (\S+)", _rule_block(title)).group(1)
        assert url.endswith(f"docs/runbooks/{title}.md")
        assert (ROOT / "docs" / "runbooks" / f"{title}.md").exists()


def test_dashboard_failure_ratio_matches_the_alert():
    panels = json.loads(DASHBOARD.read_text(encoding="utf-8"))["panels"]
    ratio = next(p for p in panels if p["title"] == "Extraction failure ratio")
    expr = ratio["targets"][0]["expr"]
    assert 'outcome="error"' in expr
    assert "unsupported_currency" not in expr
    assert any(p["title"] == "Unsupported currency (1h)" for p in panels)
