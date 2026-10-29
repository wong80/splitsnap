# 2026-10-29 — Unsupported currency (INR) crashes the organizer page

| | |
|---|---|
| **Incident issue** | #31 |
| **Fix PR** | (this PR) |
| **Alert** | HighServerErrorRate |
| **Environment** | local (on-call drill) |
| **Detected** | Alert fired after 2-minute sustained 5xx ratio |
| **Resolved** | Fix PR opened with regression tests |
| **Responder** | On-call agent (Claude Code) |

## Impact

Every request to the organizer page (`GET /b/<token>/`) for a bill extracted from an INR receipt returned HTTP 500. The probe, which uploads a receipt every 30 seconds, hit this on every cycle, producing a 5xx ratio well above the 5% threshold.

## Timeline (UTC)

- Drill traffic started with `DEMO_RECEIPT=demo_receipt_inr`
- Probe uploads produce bills with currency INR; the redirect to the admin page returns 500
- `HighServerErrorRate` goes Pending after evaluation, Firing after 2-minute hold
- Alert relay opens incident #31
- On-call agent acknowledged, queried Prometheus/Tempo/Loki
- Root cause identified from trace `460aa4457b13860bee440f10979aadc6`
- Fix PR opened with regression tests

## Root cause

`_create_bill_from_extraction` in `bills/views.py` stored the extracted currency verbatim on the Bill model, even when `run_extraction` reported `currency_supported=False`. When the organizer page rendered, `_bill_context` called `to_display(gap, bill.currency)` which called `exponent("INR")`, raising `ValueError: Unsupported currency: INR`.

**Evidence:**

- Tempo trace `460aa4457b13860bee440f10979aadc6`: server span `GET b/<str:admin_token>/` has `status=error`, exception event `ValueError: Unsupported currency: INR` at `splitting/money.py:47`.
- Prometheus: `http_server_request_duration_seconds_count` shows 500s on route `b/<str:admin_token>/`.
- Prometheus: `splitsnap_extraction_total{outcome="unsupported_currency"}` confirms INR extractions were recorded but not blocked at bill creation.

This violates plan decision D14: "An unknown currency blocks the bill until the organizer picks a supported one."

## Fix

In `_create_bill_from_extraction`, the currency is now validated with `is_supported_currency()` before being stored. If the extracted currency is not in the whitelist, the bill falls back to `"MYR"` (the default). The bill is created in REVIEW status, so the organizer can correct the currency via the review form.

### Regression tests added

- `test_bill_with_unsupported_currency_falls_back`: verifies `_create_bill_from_extraction` stores `"MYR"` when the extraction returns `"INR"`.
- `test_admin_page_renders_for_unsupported_currency_bill`: verifies the admin page returns 200, not 500.
- `test_admin_page_500_without_fix_scenario`: confirms `exponent("INR")` still raises, so the whitelist is enforced at the money layer.

## Follow-ups

- [ ] Show a warning banner on the review page when the extraction's original currency was replaced
- [ ] Consider adding INR to the supported currency whitelist if there is user demand
- [ ] Add a model-level `clean()` constraint on `Bill.currency` to reject unsupported values at the DB layer
