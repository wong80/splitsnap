# ReceiptExtractionFailing

**Meaning:** more than 20% of receipt uploads in an environment ended with outcome `error` or `unsupported_currency` over 5 minutes, sustained for 2 minutes. Organizers cannot turn photos into bills.

**Severity:** page. The dashboard is *SplitSnap - receipt journey*, in the receipt upload journey row.

## Triage

1. **Which outcome?** Run query 4 in the [toolkit](README.md#investigation-toolkit-read-only).
   - **`error`:** the model call raised. Open a `receipt.extract.attempt` span with `status=error` and read its exception event:
     - `APITimeoutError` or `TimeoutError` means the model is slow. Check `splitsnap_extraction_duration_seconds` p95 against the 30 s target.
     - `AuthenticationError` means the `ANTHROPIC_API_KEY` is wrong or expired. This is a human task (secret rotation).
     - `JSONDecodeError` or `ValidationError` means the model returned something other than the schema. Check `receipts/prompts/extract_v1.md` and `RECEIPT_MODEL`.
   - **`unsupported_currency`:** receipts are arriving in a currency outside `splitting.money.CURRENCIES`. Check whether the app handles that gracefully: the organizer should be asked to pick a supported currency rather than seeing a 500 error. `HighServerErrorRate` often fires at the same time.
2. **Is it one environment?** dev uses the demo extractor (`DEMO_RECEIPT` picks the fixture). prod uses whatever `RECEIPT_EXTRACTOR` is set to.
3. **Did the prompt or model change?** Run `git log -- receipts/prompts receipts/extraction.py` and compare with `eval_receipts`.

## Fix paths

| Cause | Who | Action |
|---|---|---|
| Code path mishandles an outcome | On-call agent | Regression test plus fix PR |
| Provider outage or slowness | Human | Wait, or switch `RECEIPT_EXTRACTOR=demo` in dev only. Note it in the incident. |
| Expired key | Human | Rotate the key in the runner environment and redeploy |

## Done when

The failure ratio is under 20%, the alert resolves, and the PR adds a test for the failing outcome.
