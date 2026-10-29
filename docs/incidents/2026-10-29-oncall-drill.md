# 2026-10-29 — On-call drill: unsupported currency crashes the organizer page

| | |
|---|---|
| **Type** | Drill (local stack, `deployment_environment_name=local`) |
| **Incident issues** | #30 `ReceiptExtractionFailing`, #31 `HighServerErrorRate` (both opened automatically by the alert relay) |
| **Fix PR** | Pending. The on-call agent is woken with `--wake-issue 31` once the repo owner approves running it |
| **Status** | Detection and incident creation verified end to end. The fix is waiting on the agent run. |

## What was exercised

```
probe (every 30 s) ──► POST /  (receipt in INR) ──► 302 ──► GET /b/<token>/ ──► 500
                                                                     │
OpenTelemetry ──► LGTM ──► Grafana rules evaluate every 30 s ──► Pending 13:52:40Z ──► Firing 13:54:40Z
                                                                                         │
                                         webhook (Bearer token) ──► ops/alert_relay.py ──┘
                                                                     ├─ 13:54:52Z  opened #30 ReceiptExtractionFailing/local
                                                                     └─ 13:54:57Z  opened #31 HighServerErrorRate/local
```

## Timeline (UTC)

- 13:51: drill traffic started: `DEMO_RECEIPT=demo_receipt_inr docker compose --profile probe up`
- 13:51: the probe's `upload` step returns HTTP 500 on every run
- 13:52:40: both rules go Pending (value 1.0, meaning 100% of extractions `unsupported_currency`; 5xx ratio 0.33)
- 13:54:40: both rules Firing, after the 2-minute hold
- 13:54:52 and 13:54:57: the relay opens incidents #30 and #31 with labels `type:incident`, `agent:oncall`, a runbook link and a dashboard link

## Root cause (from telemetry, confirmed in code)

- Tempo trace `d85097600b6535d127e472fb720d43bc`: the server span `GET b/<str:admin_token>/` has status ERROR. Its exception event is `ValueError: Unsupported currency: INR`, raised at `splitting/money.py:47` (`exponent`).
- `bills/views.py::_create_bill_from_extraction` stores `result.receipt.currency` on the Bill even when `run_extraction` reported `currency_supported=False`. Every later render calls `to_display(..., bill.currency)`, which raises.
- This contradicts plan decision D14: "An unknown currency blocks the bill until the organizer picks a supported one."

## Expected fix (for the agent's PR)

- Regression test: an upload whose extraction returns an unsupported currency leads to an organizer page that renders (200), with a prompt to pick a supported currency.
- Do not persist an unsupported currency on the Bill. Fall back to a supported default, flag the Bill as needing a currency choice, and show the warning on the review screen.

## What was not done in this drill, and why

The relay ran in `--mode issue-only`. In `--mode local`, the relay starts an autonomous Claude Code agent (`claude -p --agent oncall`) that edits code and opens a PR. That step needs the repo owner's explicit go-ahead, so it was not started by the session that built the pipeline. To finish the drill:

```bash
python ops/alert_relay.py --wake-issue 31 --alert HighServerErrorRate --env local \
  --grafana-url http://localhost:3000 --base-branch main
```
