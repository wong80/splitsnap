# 2026-10-29 — Unsupported currency (INR) crashes the organizer page

| | |
|---|---|
| **Incident issue** | #31 |
| **Fix PR** | (this PR) |
| **Alert** | HighServerErrorRate |
| **Environment** | local (on-call drill) |
| **Detected** | Alert fired after 2-minute sustained 5xx ratio |
| **Resolved** | Fix PR opened with regression tests |
| **Responder** | On-call agent (Claude Code); revised after Reviewer agent feedback |

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

The first version of the fix (on-call agent) replaced an unsupported currency with `"MYR"`. That stopped the 500s, but review found it silently relabelled amounts: INR 500.00 became RM 500.00 with no warning. The final fix follows D14:

- `Bill.extracted_currency` (migration `0003`) records the receipt's currency when it is not supported. `Bill.currency` holds `MYR` only as a placeholder, so pages render.
- The review page shows a warning naming the receipt currency. The currency field becomes a picker with no preselected value.
- `confirm` is refused (and the button disabled) while a currency choice is pending. Only an explicit supported choice in `update_bill` clears it.
- `bill.created` logs `needs_currency_choice` (a boolean; no receipt contents).

### Regression tests

`tests/integration/bills/test_views.py::TestUnsupportedCurrencyRegression` goes through HTTP with the INR demo receipt:

- `test_organizer_page_renders_with_warning`: upload, then the organizer page returns 200 and shows the warning
- `test_confirm_is_blocked_until_a_currency_is_picked`: confirm is refused; saving without a choice keeps the block; picking SGD clears it; confirm then succeeds
- `test_supported_currency_is_not_flagged`: MYR receipts are unaffected

### Alert behaviour after the fix

`HighServerErrorRate` resolves, because the pages render. `ReceiptExtractionFailing` keeps counting `unsupported_currency` as a failed extraction, by design: those organizers still can't use the currency on their receipt, which is real user impact.

## Follow-ups

- [ ] #35: changing a Bill's currency does not rescale minor units between exponents (e.g. MYR to JPY)
- [ ] Consider adding INR to the supported currency whitelist if there is demand
