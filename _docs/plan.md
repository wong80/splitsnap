# Plan: Receipt Bill Splitter

**Based on:** Scoping session, 2026-09-16 (decisions below replace a separate proposal doc)
**Feature slug:** `bill-splitter` · **Suggested location:** `docs/reppit/bill-splitter/plan.md`
**Stack:** Django 5.2 LTS · Templates + HTMX · PostgreSQL · Cloudflare R2 (S3 API) · Render · GitHub Actions

---

## Functional requirements

### Organizer (admin link)
1. **Create a bill** by uploading a receipt photo (JPEG, PNG, WEBP, HEIC; max 10 MB).
2. **Automatic extraction.** A vision LLM returns line items (description, quantity, line amount, item discount), bill-level lines (voucher/discount, service charge, tax, rounding adjustment), printed total, and currency.
3. **Review & edit screen.** The receipt image is shown beside editable items and charges. The screen shows a live **reconciliation gap**, calculated as (items − item discounts) + bill lines − printed total.
   - If the gap ≠ 0 after extraction, the system retries **once**, sending the gap back to the model as feedback.
   - If the gap is still ≠ 0, show a warning and offer a one-click **Adjustment** line, prefilled with the gap.
4. **Currency.** One per bill. It's detected by the LLM and confirmed by the organizer, with no conversion.
5. **Participants.** Add, rename, or remove them.
6. **Payers.** Record how much each participant paid; one or more payers are allowed.
7. **Lock the bill.** Locking freezes claims and computes final results. The organizer can unlock, which discards the snapshot, and re-lock.
8. **Two links.** The organizer receives a private **admin link** and a **share link** for friends.

### Friends (share link)
9. Pick **"I am …"** from the participant list, or add their own name. The choice is remembered per bill in a signed cookie.
10. **Claim items** and set **custom shares** as integer weights (e.g. "2 of 3 beers" means weights 2 and 1).
11. See live per-person totals. The page polls for other people's changes.
12. Friends **cannot** edit items, prices, charges, payments, or lock state.

### Result (both links, after lock)
13. **Summary page** containing:
    - Per-person breakdown: their items (with share), their portion of each bill-level line, and the amount owed.
    - Settlement: **who pays whom, how much**.
14. **Copy as text.** A pre-formatted plain-text summary, suitable for chat apps.

### Lock preconditions (validated server-side)
- Every item has ≥ 1 claim.
- Reconciliation gap = 0.
- Sum of payments = bill total.
- The total of all item subtotals is > 0 when any bill-level line is non-zero.

---

## Non-functional requirements

| Area | Requirement |
|---|---|
| **Correctness** | Sum of all owed amounts **equals** the bill total, exactly, in minor units. Enforced by property-based tests. |
| **Money** | All amounts are integers in the currency's minor unit (e.g. sen for MYR, whole yen for JPY). No floats anywhere. |
| **Determinism** | The same inputs always produce the same allocation and settlement. |
| **Extraction latency** | p95 < 30 s end to end, including the retry. The SDK call timeout is 45 s. |
| **LLM cost cap** | At most **2** model calls per upload. Rate limit of 10 uploads/hour per IP. |
| **Collaboration freshness** | Another user's claim is visible within ~5 s (HTMX polling). |
| **Mobile** | Usable at 360 px width; the share page is the primary mobile surface. |
| **Retention** | Unlocked drafts are purged 7 days after creation. Locked bills are purged 30 days after lock, together with their images. |

---

## Design decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Split model: itemized + flexible.** Custom shares, item and bill discounts, and multiple payers are all in the MVP. | Chosen in scoping. |
| D2 | **Custom shares are integer weights** on each claim; the default weight is 1. | Covers "2 of 3" without fractions, and reuses the same allocation function. |
| D3 | **Largest-remainder rounding.** Ties are broken by participant ID ascending. | Exact totals, deterministic, and fair. |
| D4 | **Bill-level lines come from the receipt**, not recomputed from rates. Each line is allocated separately in proportion to each person's item subtotal after item discounts. | Always matches the receipt. Per-line allocation gives a per-person breakdown for every line while keeping each line exact. |
| D5 | **Negative lines** (vouchers, rounding down) allocate the absolute value, then negate. | Keeps a single allocation code path. |
| D6 | **Settlement uses greedy matching**: largest creditor against largest debtor. | Guarantees ≤ n − 1 transfers. A true minimum-transfer solution is computationally expensive in general (NP-hard), and greedy is optimal or near-optimal for dinner-sized groups. |
| D7 | **Vision LLM extraction** sits behind a `ReceiptExtractor` protocol, with the model set by the `RECEIPT_MODEL` env var. | A classic OCR or cloud receipt API can be swapped in later. |
| D8 | **Extraction is synchronous**, with an HTMX loading indicator. | Avoids running a task queue and Redis on Render. Revisit if p95 exceeds 30 s (see Future considerations). |
| D9 | **One automatic retry with gap feedback**, then warn and offer an adjustment line. | Chosen in scoping. The retry prompt includes the computed mismatch. |
| D10 | **Two unguessable tokens per bill** (`secrets.token_urlsafe(32)`, 256-bit): `admin_token` and `share_token`. | No accounts. Same pattern as Doodle-style apps. |
| D11 | **Friend identity is a signed cookie** that maps the bill to a participant; there is no authentication. | Acceptable trust model for friends. A mis-claim is visible to everyone and correctable before lock. |
| D12 | **Concurrency: claims are one row per (item, participant)**, upserted, with last write winning per row. | Toggles don't overwrite each other, so no locking is needed. |
| D13 | **Lock stores a snapshot** (`ShareResult`, `Transfer` rows). | The summary stays stable; unlocking deletes the snapshot. |
| D14 | **Supported currencies are a whitelist** with ISO 4217 minor-unit exponents (e.g. MYR/SGD/USD/THB = 2, JPY/KRW = 0). | Avoids silent precision bugs. An unknown currency blocks the bill until the organizer picks a supported one. |
| D15 | **Receipt images are stored in private R2**, served via short-lived presigned URLs (5 min). | Render's local disk is wiped on every deploy, and the bucket must not be publicly readable. |
| D16 | **Purge runs as a daily management command**, with an R2 lifecycle rule (45 days) as a backstop. | The app deletes rows and images together; the bucket rule catches orphaned images. |
| D17 | **Assumption:** friends may add themselves as participants via the share link before lock. | Not explicitly scoped. It removes friction for the organizer, and they can still remove entries. |

---

## Technical design

### Component overview

```
Browser (Django templates + HTMX)
   │  admin link  /b/<admin_token>/...        share link  /s/<share_token>/...
   ▼
Django views ──► bills.services (claims, payments, lock, purge)
   │                    │
   │                    ├──► splitting (pure Python: money, engine, settle)   ← no Django imports
   │                    │
   ├──► receipts (images → extractor → schema → reconciliation/retry)
   │          └──► Anthropic Messages API (vision, structured JSON)
   │
   ├──► PostgreSQL (bills, items, charges, participants, claims, payments, snapshot)
   └──► Cloudflare R2 via django-storages (receipt images, private)
```

### Data model

| Model | Key fields | Notes |
|---|---|---|
| `Bill` | `id` (UUID), `admin_token` (unique), `share_token` (unique), `title`, `currency`, `status` (`extracting` / `review` / `open` / `locked`), `receipt_image`, `printed_total_minor`, `extraction_attempts`, `prompt_version`, `created_at`, `locked_at`, `expires_at` | `expires_at` is recomputed on lock and unlock |
| `LineItem` | `bill`, `position`, `description`, `quantity`, `amount_minor` (≥ 0), `item_discount_minor` (0..amount) | Net amount = `amount_minor − item_discount_minor` |
| `BillCharge` | `bill`, `kind` (`discount` / `service_charge` / `tax` / `rounding` / `adjustment` / `other`), `label`, `amount_minor` (signed) | Discounts are negative |
| `Participant` | `bill`, `name` | Name is unique per bill |
| `ItemClaim` | `line_item`, `participant`, `weight` (≥ 1) | `unique(line_item, participant)` |
| `Payment` | `bill`, `participant`, `amount_minor` (> 0) | `unique(bill, participant)` |
| `ShareResult` | `bill`, `participant`, `items_minor`, `charges_minor` (JSON per charge), `owed_minor`, `paid_minor` | Snapshot written at lock |
| `Transfer` | `bill`, `from_participant`, `to_participant`, `amount_minor` (> 0) | Snapshot written at lock |

### Splitting engine (pure domain, `splitting/`)

```python
# splitting/engine.py — illustrative signatures only
def allocate(total_minor: int, weights: Mapping[PID, int]) -> dict[PID, int]:
    """Largest-remainder split. sum(result.values()) == total_minor. Ties → lowest PID."""

def compute_shares(items: Sequence[ItemInput],
                   charges: Sequence[ChargeInput],
                   payments: Mapping[PID, int]) -> SplitResult:
    """1) allocate each item's net amount by claim weights → per-person subtotal
       2) allocate each charge by subtotals (abs value, then re-sign)
       3) owed = subtotal + charges;  net = paid − owed"""

# splitting/settle.py
def settle(net: Mapping[PID, int]) -> list[Transfer]:
    """Greedy: repeatedly match the largest debtor with the largest creditor."""
```

### Extraction pipeline (`receipts/`)

1. **Prepare the image** (`images.py`):
   - Decode with Pillow; HEIC is handled via pillow-heif.
   - Reject files that aren't images, whatever their extension.
   - Correct rotation using the photo's orientation tag, then **strip all EXIF** (removes GPS).
   - Downscale so the longest edge is ≤ 1568 px, and re-encode as JPEG.
2. **Extract** (`extraction.py`): `AnthropicExtractor.extract(image, feedback=None) -> ExtractedReceipt`.
   - The prompt lives in `receipts/prompts/extract_v1.md`, and its version is stored on the bill.
   - The model must return JSON matching a Pydantic schema. Amounts come back as **decimal strings**, never numbers.
3. **Parse** (`schema.py`): Pydantic validation, then `Decimal` → minor units using the currency exponent. Extra precision is rejected. If the schema is invalid, the attempt counts as a failure.
4. **Reconcile** (`validation.py`): compute the gap.
   - If gap ≠ 0 and attempts < 2, call again with feedback, e.g. *"Your items and charges sum to 98.40 but the printed total is 100.00; re-read the receipt."*
   - Otherwise, set status to `review` and surface the gap to the organizer.
5. `FakeExtractor` returns fixtures for tests and local dev; select it with `RECEIPT_EXTRACTOR=fake`.

### HTMX interaction patterns
- **Claim toggle and weight stepper:** `hx-post` → server upserts the claim → returns the item row partial plus an out-of-band swap of the totals panel.
- **Share page refresh:** `hx-get` on the claims and totals region with `hx-trigger="every 5s"`, paused while an input has focus.
- **Review screen:** each edit re-renders the reconciliation banner.
- **CSRF:** `hx-headers` on `<body>` carries the CSRF token.

---

## Files & integration points

```
.
├── pyproject.toml / uv.lock           # dependencies, ruff + pytest config
├── render.yaml                        # web service, Postgres, cron job (Blueprint)
├── .github/workflows/
│   ├── ci.yml                         # lint, migrations check, tests, deploy checks
│   └── eval.yml                       # golden-set extraction eval (manual + nightly)
├── config/
│   ├── settings/{base,dev,prod}.py    # env-driven; prod: DEBUG off, security headers
│   ├── urls.py
│   └── wsgi.py
├── core/
│   ├── views.py                       # /healthz (DB check)
│   ├── middleware.py                  # Referrer-Policy, X-Robots-Tag: noindex, request ID
│   └── logging.py                     # JSON log formatter, token redaction filter
├── splitting/                         # PURE PYTHON — no Django imports
│   ├── money.py                       # currency whitelist, Decimal ↔ minor, formatting
│   ├── engine.py                      # allocate(), compute_shares()
│   └── settle.py                      # settle()
├── receipts/
│   ├── images.py
│   ├── schema.py                      # Pydantic ExtractedReceipt
│   ├── extraction.py                  # ReceiptExtractor protocol, Anthropic + Fake
│   ├── validation.py                  # reconciliation + retry orchestration
│   ├── prompts/extract_v1.md
│   └── management/commands/eval_receipts.py
├── bills/
│   ├── models.py
│   ├── forms.py
│   ├── urls.py                        # /b/<admin_token>/…, /s/<share_token>/…
│   ├── views/{create,review,admin,share,summary}.py
│   ├── services/{claims,payments,lock,purge}.py
│   ├── templates/bills/*.html + partials/*.html + summary.txt
│   └── management/commands/purge_expired_bills.py
├── evals/receipts/                    # <name>.jpg + <name>.expected.json (redacted)
└── tests/
    ├── splitting/  test_money.py, test_engine_cases.py, test_engine_properties.py, test_settle.py
    ├── receipts/   test_images.py, test_schema.py, test_reconcile_retry.py
    └── bills/      test_models.py, test_access_control.py, test_claims_views.py,
                    test_lock.py, test_summary_text.py, test_purge.py
```

**Key dependencies:**
- **Runtime:** `django`, `psycopg[binary]`, `dj-database-url`, `django-htmx`, `django-storages[s3]`, `boto3`, `anthropic`, `pydantic`, `pillow`, `pillow-heif`, `gunicorn`, `whitenoise`, `django-ratelimit`, `sentry-sdk`, `python-json-logger`
- **Dev:** `pytest`, `pytest-django`, `hypothesis`, `coverage`, `ruff`

---

## Implementation steps

| # | Step | Depends on | Parallel? |
|---|---|---|---|
| 1 | **Walking skeleton.** Django project, settings split, `/healthz`, ruff, pytest, `ci.yml` with a Postgres service, `render.yaml`. Deploy "hello" to Render with auto-deploy after CI passes. | none | none |
| 2 | **Splitting engine.** `money.py`, `allocate`, `compute_shares`, `settle`, plus named case tests and Hypothesis property tests. Coverage gate: 95% on `splitting/`. | 1 | with 3, 4 |
| 3 | **Models & token routing.** Migrations, token generation, admin/share URL resolvers, 404 on unknown tokens, access-control tests. | 1 | with 2, 4 |
| 4 | **Extraction module.** Image preparation, schema, `FakeExtractor`, `AnthropicExtractor`, reconciliation + single retry, all unit tested with mocks. | 1 | with 2, 3 |
| 5 | **Upload + review screen.** Create bill, run extraction, edit items/charges, reconciliation banner, adjustment line, currency confirm. | 3, 4 | none |
| 6 | **Participants & claims (HTMX).** Organizer participant management, share-page identity cookie, claim toggles, weight stepper, polling, live totals via the engine. | 2, 3 | with 5 |
| 7 | **Payments, lock, summary.** Payment entry, lock validation, snapshot write, unlock, summary page, `summary.txt` + copy button. | 2, 6 | none |
| 8 | **Storage & retention.** R2 via django-storages, presigned URLs, `purge_expired_bills`, Render cron job, R2 lifecycle rule. | 3, 5 | with 9 |
| 9 | **Observability.** JSON logging with token redaction, extraction event logs, Sentry, request IDs. | 1 (wire early), 4, 7 | with 8 |
| 10 | **Golden-set eval.** Collect and redact 10–15 receipts, write expected JSON, `eval_receipts` command, `eval.yml` (manual + nightly) writing a Markdown job summary. | 4 | from step 5 onward |
| 11 | **Hardening & docs.** Rate limiting, `check --deploy` clean, security headers, error pages, README (setup, env vars, architecture, trade-offs). | 7, 8 | none |

---

## Testing strategy

### Splitting engine: the core, blocks merge
**Named cases** (table-driven):
- 10.00 split three ways gives 3.34 / 3.33 / 3.33.
- Weights 2:1 on one item.
- An item discount.
- A negative voucher.
- A rounding line of −0.02.
- A participant with no claims but who is a payer.
- A JPY bill with exponent 0.
- Two payers, three debtors.

**Property-based tests** (Hypothesis, random bills):
- `sum(owed) == bill_total` always.
- `sum(allocate(t, w)) == t` for any `t` and positive weights.
- Each allocation differs from its exact proportional value by < 1 minor unit.
- Same input always gives the same output; shuffling input order doesn't change results.
- If all bill-level lines are ≥ 0, every `owed ≥ 0`.
- Settlement: applying transfers zeroes every net balance, `len(transfers) ≤ n − 1`, and every amount > 0.

### Receipts: blocks merge
- **Images:** a HEIC fixture decodes, EXIF is stripped (no GPS tag in output), resize bounds hold, non-images are rejected.
- **Schema:** decimal strings convert correctly, excess precision is rejected, unknown currencies are flagged.
- **Retry logic** (mocked extractor):
  - Match on the first call means one call.
  - Mismatch then match means two calls, and the feedback contains the gap.
  - Mismatch twice means two calls, `review` status, and the gap surfaced.
  - An invalid schema response counts as an attempt.
  - Never more than 2 calls.

### Bills / views: blocks merge (pytest-django)
- **Access control:**
  - Share token → POST to item/price/charge/payment/lock endpoints returns 403/404.
  - An unknown token returns 404.
  - An admin token never appears in share-page HTML.
- **Claims:** upsert idempotency, weight validation, rejection after lock.
- **Lock:** each precondition fails with a clear message; a successful lock writes a snapshot that matches the engine; unlock clears it.
- **Summary text:** snapshot test of `summary.txt` rendering.
- **Purge:** expired bills and their storage objects are deleted, non-expired ones untouched (storage mocked).

### CI checks (GitHub Actions)
- `ruff check`
- `ruff format --check`
- `manage.py makemigrations --check`
- `manage.py check --deploy` (prod settings)
- `pytest` with coverage

### Golden-set eval: on demand + nightly, non-blocking
`manage.py eval_receipts` reports:
- Printed-total exact-match rate.
- Currency accuracy.
- Item-level precision and recall, where a match means amount is exact and description is fuzzy-matched.
- Reconciliation pass rate.
- Average attempts, latency, and token usage.

The report is written as the GitHub job summary. Compare runs before and after any prompt or model change.

### Manual / agentic review before "done"
- End-to-end on a phone:
  1. Upload a real receipt.
  2. Fix a mis-read item.
  3. Two browsers claim concurrently.
  4. Two payers.
  5. Lock.
  6. Copy the text into a chat app.
- Review against this plan using the `test` step.

---

## Observability

| Signal | Implementation |
|---|---|
| **Structured logs** | JSON to stdout (collected by Render). A redaction filter replaces tokens with an 8-character prefix. |
| **Extraction events** | `receipt.extraction.completed` with `bill_id`, `attempt`, `model`, `prompt_version`, `latency_ms`, `input_tokens`, `output_tokens`, `gap_minor`, `outcome` (`matched` / `retried_matched` / `needs_review` / `schema_error` / `api_error`). |
| **Domain events** | `bill.created`, `bill.locked` (participants, items, payers, transfers), `bill.unlocked`, `purge.completed` (rows and objects deleted). |
| **Errors** | Sentry for Django and the management commands. Scrub token path segments with a `before_send` hook. |
| **Health** | `/healthz` returns 200 only if a DB query succeeds, and is used as Render's health check. |
| **Watch first** | `needs_review` rate, extraction p95 latency, `api_error` count, purge job last success. Initially derived from logs; dashboards and alerts come in the course's observability module. |

---

## Future considerations (explicitly out of scope)

Do **not** implement any of the following in this change:
- User accounts, login, email/magic links, or persistent groups and balances across bills.
- Currency conversion or exchange-rate APIs.
- "Mark as paid" tracking, payment QR codes, or any payment or bank integration.
- Background task queue (Celery, RQ, Redis, django-tasks). Extraction stays synchronous (D8).
- WebSockets or server-sent events; polling is sufficient.
- Automatically splitting a `quantity > 1` line into separate units. Weights cover this.
- Recomputing tax or service charge from percentage rates.
- Alternative extractors (Tesseract, Textract, Document AI). The protocol exists; implementations don't.
- Regenerating or revoking admin/share tokens.
- Multiple receipts per bill, or editing a bill after purge.
- Internationalization of UI text (English only), PWA or offline support.
- Playwright or browser end-to-end automation. Manual smoke review only for now.
- Refactoring anything outside this project's apps.

---

## Dependencies

| Dependency | Status / note |
|---|---|
| GitHub repository + Actions | Needed at step 1. |
| Render account: web service + Postgres | **Free Postgres expires after ~30 days**; upgrade or re-seed before the demo or submission. |
| Render cron job | Cron jobs are billed. Alternative: rely on the R2 lifecycle rule for images, plus purge on app startup. |
| Anthropic API key | Needed as a Render env var and a GitHub Actions secret (eval workflow only). |
| Cloudflare R2 bucket + access keys | Private bucket; add the 45-day lifecycle rule. |
| Sentry DSN | Free tier is sufficient. |
| Golden receipts (10–15) | Collect yourself; redact card digits and names before committing. |
| Python 3.12, uv | Local and CI toolchain. |

---

## Security

| Risk | Mitigation |
|---|---|
| **Token leakage** | 256-bit tokens. `Referrer-Policy: same-origin`; `X-Robots-Tag: noindex`; tokens redacted in app logs and Sentry. Accepted risk: Render's own request logs contain full URLs. |
| **Share link escalation** | All write endpoints except claims, weights, and self-add require the admin token, resolved server-side. Covered by access-control tests. |
| **Prompt injection via receipt image** | Model output is treated as untrusted data only. It is validated against the Pydantic schema, never executed or used as instructions, and always rendered through Django's escaping of HTML. |
| **Malicious uploads** | 10 MB limit; decoded with Pillow; re-encoded to JPEG; stored under random keys; never served from the app domain. |
| **Privacy (PII in receipts, photo GPS)** | EXIF stripped; private bucket; presigned URLs (5 min); retention purge. |
| **LLM cost abuse** | Per-IP upload rate limit, max 2 calls per upload, SDK timeout. |
| **Standard web** | CSRF on all POSTs (HTMX headers); `SECURE_*` settings, HSTS, secure cookies; `DEBUG=False`; secrets only in env vars; `check --deploy` in CI. |

---

## Rollout

- **Environments:** local (`dev` settings, `FakeExtractor` default) → Render production (`prod` settings). No staging; CI is the gate.
- **Deploy:** Render auto-deploys on push to `main` **after CI checks pass**.
- **Migrations:** run `manage.py migrate` in the Render pre-deploy command, or in the build command on free instances. Keep migrations backward-compatible: add a column first, backfill, then remove in a later deploy.
- **Feature flags:** none. Use `RECEIPT_EXTRACTOR=fake|anthropic` as the kill switch if the API misbehaves; the organizer can still enter items manually on the review screen.
- **Rollback:** Render "rollback to previous deploy". Destructive migrations are not allowed in this plan.
- **Launch checklist:**
  - `check --deploy` clean.
  - Env vars set.
  - R2 lifecycle rule active.
  - Cron job scheduled.
  - Sentry receiving events.
  - Golden-set eval baseline recorded.
