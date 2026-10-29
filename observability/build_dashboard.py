"""Generate observability/grafana/dashboards/splitsnap.json (run: python observability/build_dashboard.py)."""

import json
from pathlib import Path

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
TEMPO = {"type": "tempo", "uid": "tempo"}
ENV = 'deployment_environment_name=~"$env"'
_id = iter(range(1, 100))


def panel(title, kind, x, y, w, h, targets, ds=PROM, unit=None, desc="", **extra):
    p = {
        "id": next(_id),
        "title": title,
        "description": desc,
        "type": kind,
        "datasource": ds,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": targets,
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {},
    }
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    p.update(extra)
    return p


def prom(expr, legend="", ref="A"):
    return {"datasource": PROM, "expr": expr, "legendFormat": legend, "refId": ref}


def row(title, y):
    return {
        "id": next(_id),
        "type": "row",
        "title": title,
        "collapsed": False,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
        "panels": [],
    }


# "or vector(0)" keeps the ratio at 0 (not "No data") when there are no failures.
failure_ratio = (
    f'(sum(rate(splitsnap_extraction_total{{outcome=~"error|unsupported_currency",{ENV}}}[5m])) or vector(0))'
    f" / clamp_min(sum(rate(splitsnap_extraction_total{{{ENV}}}[5m])), 1e-9)"
)
error_5xx_ratio = (
    f'(sum(rate(http_server_request_duration_seconds_count{{http_response_status_code=~"5..",{ENV}}}[5m])) or vector(0))'
    f" / clamp_min(sum(rate(http_server_request_duration_seconds_count{{{ENV}}}[5m])), 1e-9)"
)
thresholds = {
    "mode": "absolute",
    "steps": [
        {"color": "green", "value": None},
        {"color": "orange", "value": 0.05},
        {"color": "red", "value": 0.2},
    ],
}

panels = [
    row("Receipt upload journey (key user journey)", 0),
    panel(
        "Extraction failure ratio",
        "stat",
        0,
        1,
        6,
        5,
        [prom(failure_ratio, "failure ratio")],
        unit="percentunit",
        desc="error + unsupported_currency over all extractions (5m). Alert > 20%.",
        fieldConfig={
            "defaults": {
                "unit": "percentunit",
                "thresholds": thresholds,
                "color": {"mode": "thresholds"},
            },
            "overrides": [],
        },
    ),
    panel(
        "Extractions / min by outcome",
        "timeseries",
        6,
        1,
        9,
        8,
        [
            prom(
                f"sum by (outcome) (rate(splitsnap_extraction_total{{{ENV}}}[5m])) * 60",
                "{{outcome}}",
            )
        ],
    ),
    panel(
        "Extraction latency p50 / p95",
        "timeseries",
        15,
        1,
        9,
        8,
        [
            prom(
                f"histogram_quantile(0.5, sum by (le) (rate(splitsnap_extraction_duration_seconds_bucket{{{ENV}}}[5m])))",
                "p50",
            ),
            prom(
                f"histogram_quantile(0.95, sum by (le) (rate(splitsnap_extraction_duration_seconds_bucket{{{ENV}}}[5m])))",
                "p95",
                "B",
            ),
        ],
        unit="s",
        desc="Spec target: p95 < 30 s including the retry.",
    ),
    panel(
        "Bills locked (1h)",
        "stat",
        0,
        6,
        6,
        3,
        [prom(f"sum(increase(splitsnap_bills_locked_total{{{ENV}}}[1h]))", "locked")],
    ),
    row("HTTP (RED)", 9),
    panel(
        "Requests / s by route and status",
        "timeseries",
        0,
        10,
        12,
        8,
        [
            prom(
                f"sum by (http_route, http_response_status_code) (rate(http_server_request_duration_seconds_count{{{ENV}}}[5m]))",
                "{{http_route}} {{http_response_status_code}}",
            )
        ],
        unit="reqps",
    ),
    panel(
        "5xx ratio",
        "timeseries",
        12,
        10,
        6,
        8,
        [prom(error_5xx_ratio, "5xx")],
        unit="percentunit",
        desc="Alert > 5% for 5m.",
    ),
    panel(
        "p95 latency by route",
        "timeseries",
        18,
        10,
        6,
        8,
        [
            prom(
                f"histogram_quantile(0.95, sum by (le, http_route) (rate(http_server_request_duration_seconds_bucket{{{ENV}}}[5m])))",
                "{{http_route}}",
            )
        ],
        unit="s",
    ),
    row("Correlated logs and traces", 18),
    panel(
        "Application logs (click trace_id to open the trace)",
        "logs",
        0,
        19,
        12,
        10,
        [
            {
                "datasource": LOKI,
                "refId": "A",
                "expr": '{service_name="splitsnap", deployment_environment_name=~"$env"} | severity_text=~"INFO|WARNING|ERROR"',
            }
        ],
        ds=LOKI,
        options={
            "showTime": True,
            "wrapLogMessage": True,
            "enableLogDetails": True,
            "sortOrder": "Descending",
        },
    ),
    panel(
        "Recent receipt extraction traces",
        "table",
        12,
        19,
        12,
        10,
        [
            {
                "datasource": TEMPO,
                "refId": "A",
                "queryType": "traceql",
                "limit": 20,
                "tableType": "traces",
                "query": '{resource.service.name="splitsnap" && name="receipt.extract"}',
            }
        ],
        ds=TEMPO,
    ),
]

dashboard = {
    "uid": "splitsnap",
    "title": "SplitSnap - receipt journey",
    "tags": ["splitsnap"],
    "timezone": "browser",
    "refresh": "30s",
    "time": {"from": "now-1h", "to": "now"},
    "schemaVersion": 39,
    "templating": {
        "list": [
            {
                "name": "env",
                "label": "Environment",
                "type": "query",
                "datasource": PROM,
                "query": {
                    "query": "label_values(target_info, deployment_environment_name)",
                    "refId": "env",
                },
                "definition": "label_values(target_info, deployment_environment_name)",
                "includeAll": True,
                "multi": True,
                "allValue": ".*",
                "refresh": 2,
                "current": {"text": "All", "value": "$__all"},
            }
        ]
    },
    "panels": panels,
}

out = Path(__file__).parent / "grafana" / "dashboards" / "splitsnap.json"
out.write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8")
print(f"wrote {out}")
