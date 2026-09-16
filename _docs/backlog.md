# Backlog

Derived from `plan.md` and `grilling-amendments.md`. Tasks are grouped by implementation step. Within each step, tasks are ordered by dependency. Parallel-safe tasks within a step are marked `[parallel]`.

Status: `[ ]` todo · `[x]` done · `[-]` skipped

---

## Step 1 — Walking skeleton

- [x] Django project with `config/` settings split (`base`, `dev`, `prod`)
- [x] `/healthz` endpoint with DB check in `core/`
- [x] `splitting/` pure Python package (stubs)
- [x] `bills/`, `receipts/` Django apps created
- [x] Add `ruff` config to `pyproject.toml` (linting + formatting)
- [x] Add `pytest` + `pytest-django` config to `pyproject.toml`
- [x] `conftest.py` with Django settings override for tests
- [x] GitHub Actions `ci.yml`: ruff check, ruff format --check, migrations check, pytest with Postgres service
- [x] `render.yaml` Blueprint: web service, Postgres, cron job placeholder
- [-] Deploy "hello" to Render with auto-deploy on CI pass

---

## Step 2 — Splitting engine `[parallel with 3, 4]`

### `splitting/money.py`
- [x] Currency whitelist with ISO 4217 minor-unit exponents (MYR, SGD, USD, THB=2; JPY, KRW=0; extend as needed)
- [x] `Decimal` string to minor-unit integer conversion (reject excess precision)
- [x] Minor-unit integer to display string formatting (e.g. `2350` → `"23.50"`)
- [x] Currency symbol/code lookup for display

### `splitting/engine.py`
- [x] `allocate(total_minor, weights)` — largest-remainder split, ties broken by participant ID ascending
- [x] `compute_shares(items, charges, payments)` — full allocation pipeline:
  - Allocate each item's net amount (`amount - item_discount`) by claim weights
  - Compute per-person item subtotal
  - Allocate each bill charge by subtotals (absolute value, then re-sign for negatives)
  - `owed = subtotal + charges`; `net = paid - owed`

### `splitting/settle.py`
- [x] `settle(net_balances)` — greedy matching: largest debtor pays largest creditor, repeat
- [x] Guarantee: ≤ n−1 transfers, all amounts > 0, applying transfers zeroes all balances

### Tests (`tests/splitting/`)
- [x] Named case tests (table-driven):
  - 10.00 split three ways → 3.34 / 3.33 / 3.33
  - Weights 2:1 on one item
  - Item discount
  - Negative voucher (bill charge)
  - Rounding line of −0.02
  - Participant with no claims but is a payer
  - JPY bill (exponent 0)
  - Two payers, three debtors
  - Negative owed (large voucher, small item subtotal — person becomes creditor)
- [x] Hypothesis property tests:
  - `sum(owed) == bill_total` always
  - `sum(allocate(t, w)) == t` for any `t` and positive weights
  - Each allocation off by < 1 minor unit from exact proportion
  - Deterministic: same input → same output; shuffled input order → same result
  - Non-negative owed when all bill-level lines ≥ 0
  - Settlement: transfers zero all nets, `len(transfers) ≤ n−1`, all amounts > 0
- [x] Coverage gate: 95% on `splitting/`

---

## Step 3 — Models & token routing `[parallel with 2, 4]`

### Models (`bills/models.py`)
- [x] `Bill`: UUID pk, `admin_token` (unique, 256-bit), `share_token` (unique, 256-bit), `title`, `currency`, `status` (`extracting`/`review`/`open`/`locked`), `receipt_image`, `printed_total_minor`, `extraction_attempts`, `prompt_version`, timestamps (`created_at`, `locked_at`, `expires_at`)
- [x] `LineItem`: FK to Bill, `position`, `description`, `quantity` (default 1), `amount_minor` (≥0), `item_discount_minor` (0..amount)
- [x] `BillCharge`: FK to Bill, `kind` enum (`discount`/`service_charge`/`tax`/`rounding`/`adjustment`/`other`), `label`, `amount_minor` (signed)
- [x] `Participant`: FK to Bill, `name` (case-insensitive unique per bill, whitespace-trimmed)
- [x] `ItemClaim`: FK to LineItem + Participant, `weight` (1..quantity), unique together
- [x] `Payment`: FK to Bill + Participant, `amount_minor` (>0), unique together
- [x] `SplitSnapshot` (renamed from ShareResult): FK to Bill + Participant, `items_minor`, `charges_minor` (JSON), `owed_minor`, `paid_minor`
- [x] `Transfer`: FK to Bill + from/to Participant, `amount_minor` (>0)
- [x] Soft cap validation: max 20 participants per bill

### Token routing & access control
- [x] URL resolvers: `/b/<admin_token>/...` (admin), `/s/<share_token>/...` (share)
- [x] Lookup middleware/mixin: resolve token → Bill, 404 on unknown
- [x] Access control: share token can only POST to claim/weight/self-add endpoints; all other writes require admin token
- [x] Admin token never appears in share-page HTML responses

### Tests (`tests/bills/`)
- [x] Token generation produces 256-bit tokens
- [x] Unknown token → 404
- [x] Share token POST to item/price/charge/payment/lock → 403 or 404
- [x] Admin token not leaked in share-page responses
- [x] Migrations generated and checked

---

## Step 4 — Extraction module `[parallel with 2, 3]`

### Image preparation (`receipts/images.py`)
- [ ] Decode with Pillow; HEIC via pillow-heif
- [ ] Reject non-image files regardless of extension
- [ ] Correct rotation from EXIF orientation tag, then strip all EXIF (GPS removed)
- [ ] Downscale longest edge to ≤ 1568 px, re-encode as JPEG
- [ ] Add `pillow` and `pillow-heif` to dependencies

### Schema (`receipts/schema.py`)
- [ ] Pydantic `ExtractedReceipt` model: items (description, quantity, amount as decimal string, item_discount), charges (kind, label, amount), printed_total, currency, title
- [ ] Decimal string → minor unit conversion using currency exponent
- [ ] Reject excess precision
- [ ] Flag unsupported currencies (don't reject — pass through for review screen picker)

### Extraction (`receipts/extraction.py`)
- [ ] `ReceiptExtractor` protocol with `extract(image, feedback=None)` signature
- [ ] `AnthropicExtractor`: Anthropic Messages API with vision, structured JSON output, `RECEIPT_MODEL` env var
- [ ] `FakeExtractor`: returns fixtures for tests and local dev (`RECEIPT_EXTRACTOR=fake`)
- [ ] Prompt in `receipts/prompts/extract_v1.md` — extract items, charges, printed total, currency, title (restaurant/shop name)
- [ ] Store `prompt_version` on Bill
- [ ] SDK call timeout: 45s
- [ ] Add `anthropic` and `pydantic` to dependencies

### Reconciliation & retry (`receipts/validation.py`)
- [ ] Compute gap: `sum(item nets) + sum(charges) − printed_total`
- [ ] If gap ≠ 0 and attempts < 2: retry with feedback ("items sum to X but printed total is Y")
- [ ] Retry fully replaces attempt 1's items and charges
- [ ] If gap still ≠ 0 after retry: set status to `review`, surface gap
- [ ] Invalid schema response counts as a failed attempt
- [ ] Never more than 2 LLM calls per upload
- [ ] Unsupported currency: not a schema error, bill enters `review` with items intact
- [ ] Both attempts fail: bill enters `review` with empty items
- [ ] Title extraction fallback: date-based title if LLM doesn't extract one

### Tests (`tests/receipts/`)
- [ ] HEIC fixture decodes correctly
- [ ] EXIF stripped (no GPS tag in output)
- [ ] Resize bounds hold (longest edge ≤ 1568)
- [ ] Non-image files rejected
- [ ] Decimal strings convert correctly to minor units
- [ ] Excess precision rejected
- [ ] Unsupported currency flagged (not rejected)
- [ ] Retry logic (mocked extractor):
  - Match on first call → one call total
  - Mismatch then match → two calls, feedback contains gap
  - Mismatch twice → two calls, `review` status, gap surfaced
  - Invalid schema → counts as attempt
  - Never more than 2 calls

---

## Step 5 — Upload + review screen

### Upload flow
- [ ] Create bill view: file upload form (JPEG, PNG, WEBP, HEIC; max 10 MB)
- [ ] Per-IP rate limit: 10 uploads/hour, clear error with time estimate on 429
- [ ] On upload: set status `extracting`, run extraction synchronously
- [ ] Show spinner via `hx-indicator` during the long POST
- [ ] On completion: redirect to review screen (or render it as response)

### Review screen
- [ ] Receipt image displayed (collapsible on mobile, beside editor on desktop)
- [ ] Presigned URL for image with 5-min expiry
- [ ] Lazy presigned URL refresh: HTMX endpoint, `hx-trigger="load, every 240s"`
- [ ] Editable fields: title, currency (picker for unsupported), printed total, all line items, all bill charges
- [ ] Add/delete line items and bill charges
- [ ] `quantity` field on each item (default 1, editable)
- [ ] Reconciliation gap banner: live recompute on every edit
- [ ] One-click adjustment line button (prefilled with gap) when gap ≠ 0
- [ ] "Confirm" button to transition `review → open`

### Status machine
- [ ] `extracting → review`: automatic after extraction completes
- [ ] `review → open`: explicit "Confirm" action
- [ ] `open → review`: allowed, with warning about existing claims; auto-clamp weights if quantity edited down; drop claims on deleted items

---

## Step 6 — Participants & claims (HTMX) `[parallel with 5]`

### Organizer side (admin page)
- [ ] Add/rename/remove participants
- [ ] Admin page polls every 5s for live claim updates
- [ ] Show per-item claim details (who claimed, weights)
- [ ] Show live per-person totals via the splitting engine

### Share page — identity
- [ ] "I am..." picker from existing participant list
- [ ] "Add myself" field: if name matches existing (case-insensitive) → select that participant; otherwise create new (up to 20 cap)
- [ ] Signed cookie maps bill → participant; remembered per bill
- [ ] "Not [name]? Switch" link: clears cookie, returns to identity picker; claims stay on original participant
- [ ] Before identity selection: item list visible read-only, interactions disabled
- [ ] In `extracting`/`review` status: waiting screen with "organizer is still setting up" + polling

### Share page — claims
- [ ] Claim toggle: `hx-post` → upsert claim (weight=1) or delete claim
- [ ] Weight stepper: shown only after item is claimed; range 1..quantity
- [ ] `hx-post` → server upserts claim → returns item row partial + OOB totals swap
- [ ] Full claim visibility: each friend sees all participants' claims and weights per item
- [ ] Polling: `hx-get` on claims + totals region, `hx-trigger="every 5s"`, paused while input has focus
- [ ] After lock: server-side 302 redirect to summary; HTMX polling sends `HX-Redirect`
- [ ] Friends cannot edit items, prices, charges, payments, or lock state

### Tests
- [ ] Claim upsert idempotency
- [ ] Weight validation (1..quantity, clamping on quantity edit)
- [ ] Claims rejected after lock
- [ ] Self-add respects 20-participant cap
- [ ] Self-add name collision → selects existing participant

---

## Step 7 — Payments, lock, summary

### Payments
- [ ] "Add payer" button on admin page: pick participant, enter amount
- [ ] One payment per participant (`unique(bill, participant)`)
- [ ] Running total display: "Payments: RM X / RM Y"
- [ ] Payment section below claims area on admin page

### Lock
- [ ] Live precondition checklist on admin page (check/cross per condition):
  - Every item has ≥ 1 claim
  - Reconciliation gap = 0
  - Sum of payments = printed total
  - Sum of item subtotals > 0 when any bill charge is nonzero
- [ ] Lock button enabled only when all preconditions pass
- [ ] On lock: write `SplitSnapshot` + `Transfer` rows, set `locked_at`, compute `expires_at` (30 days)
- [ ] Snapshot matches engine output exactly

### Unlock
- [ ] Returns bill to `open` status
- [ ] Deletes snapshot (`SplitSnapshot` + `Transfer` rows)
- [ ] Recomputes `expires_at` (7 days from creation)

### Summary page
- [ ] Admin page (`/b/<token>/`): renders summary content when bill is locked (one morphing URL)
- [ ] Share page: 302 redirect to `/s/<token>/summary` when locked
- [ ] Web summary: full per-person breakdown — claimed items with share and amount, portion of each charge, owed, paid, net, settlement transfers
- [ ] Plain-text summary: settlement + per-person totals (concise, chat-friendly)
- [ ] "Copy as text" button (Clipboard API)

### Tests
- [ ] Each lock precondition fails with a clear message
- [ ] Successful lock writes snapshot matching engine output
- [ ] Unlock clears snapshot
- [ ] Summary text snapshot test
- [ ] Payment validation (positive amounts, unique per participant)

---

## Step 8 — Storage & retention `[parallel with 9]`

- [ ] Add `django-storages[s3]` and `boto3` to dependencies
- [ ] Configure R2 via `django-storages` in prod settings (private bucket, S3 API)
- [ ] Receipt images stored under random keys in R2
- [ ] Presigned URL generation (5-min expiry) for image display
- [ ] `purge_expired_bills` management command:
  - Delete unlocked bills older than 7 days from creation
  - Delete locked bills older than 30 days from lock
  - Delete associated R2 objects
- [ ] Render cron job in `render.yaml` (daily)
- [ ] R2 lifecycle rule (45 days) as backstop for orphaned images
- [ ] `expires_at` recomputed on lock (30 days) and unlock (7 days from creation)

### Tests
- [ ] Expired bills and storage objects deleted (storage mocked)
- [ ] Non-expired bills untouched
- [ ] `expires_at` correctly set on lock and unlock

---

## Step 9 — Observability `[parallel with 8]`

- [ ] Add `python-json-logger` and `sentry-sdk` to dependencies
- [ ] JSON log formatter for structured logs to stdout
- [ ] Token redaction filter: replace admin/share tokens with 8-char prefix in logs
- [ ] Extraction events: `receipt.extraction.completed` with bill_id, attempt, model, prompt_version, latency_ms, tokens, gap, outcome
- [ ] Domain events: `bill.created`, `bill.locked`, `bill.unlocked`, `purge.completed`
- [ ] Sentry integration for Django + management commands
- [ ] Sentry `before_send` hook: scrub token path segments
- [ ] Request ID middleware in `core/middleware.py`
- [ ] `Referrer-Policy: same-origin` header
- [ ] `X-Robots-Tag: noindex` header

---

## Step 10 — Golden-set eval

- [ ] Collect and redact 10–15 receipt images (`evals/receipts/<name>.jpg`)
- [ ] Write expected JSON per receipt (`evals/receipts/<name>.expected.json`)
- [ ] `eval_receipts` management command reporting:
  - Printed-total exact-match rate
  - Currency accuracy
  - Item-level precision and recall (amount exact, description fuzzy-matched)
  - Reconciliation pass rate
  - Average attempts, latency, token usage
- [ ] GitHub Actions `eval.yml`: manual trigger + nightly, writes Markdown job summary
- [ ] Baseline recording before any prompt/model change

---

## Step 11 — Hardening & docs

- [ ] Add `django-ratelimit` to dependencies; wire rate limiting on upload endpoint
- [ ] `manage.py check --deploy` clean with prod settings
- [ ] Security headers: `SECURE_*` settings, HSTS, secure cookies
- [ ] CSRF via `hx-headers` on `<body>` for all HTMX POSTs
- [ ] Custom 404 error page (generic, covers purged bills)
- [ ] Custom 500 error page
- [ ] Add `whitenoise` for static file serving; configure `STATIC_ROOT`
- [ ] Add `gunicorn` to dependencies; configure in `render.yaml`
- [ ] README: setup instructions, env vars, architecture overview, trade-offs
