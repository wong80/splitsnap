# SplitSnap

**Snap a receipt, split the bill — exactly.**

[![CI](https://github.com/wong80/splitsnap/actions/workflows/ci.yml/badge.svg)](https://github.com/wong80/splitsnap/actions/workflows/ci.yml)
[![CD dev](https://github.com/wong80/splitsnap/actions/workflows/cd-dev.yml/badge.svg)](https://github.com/wong80/splitsnap/actions/workflows/cd-dev.yml)

## The problem

After a group meal, one person pays and then has to work out who owes what. That is tedious and easy to get wrong:

- **Typing in the receipt is slow.** A typical receipt has 10–20 lines, plus service charge, tax, vouchers and rounding.
- **Splitting is not simply "divide by N."** People order different things, share some dishes unevenly ("I had 2 of the 3 beers"), and bill-level charges like service and tax should follow what each person actually ate.
- **Rounding leaks money.** Splitting RM 10.00 three ways gives 3.33 + 3.33 + 3.33 = 9.99. Somebody has to absorb the missing sen, and floating-point maths makes it worse.
- **Settling up takes too many transfers** when several people paid part of the bill.

SplitSnap turns a receipt photo into a fair, exact settlement that everyone can check, with no accounts and no app install.

## What it does

| Step | Who | What happens |
|---|---|---|
| 1. **Upload** | Organizer | Takes a photo of the receipt (JPEG, PNG, WEBP or HEIC, up to 10 MB). EXIF and GPS data are stripped. |
| 2. **Extract** | System | A vision LLM (Anthropic Claude) reads the line items, item discounts, bill-level charges (tax, service, vouchers, rounding), the printed total and the currency. If the lines don't add up to the printed total, it retries **once** with the gap as feedback. |
| 3. **Review** | Organizer | Edits items and charges while watching a live **reconciliation gap** (items + charges − printed total). A one-click adjustment line covers small mismatches. Confirming moves the bill to *open*. |
| 4. **Share** | Organizer → Friends | The organizer gets a private **admin link** and sends friends a **share link**. Both are unguessable 256-bit tokens, so nobody needs an account. |
| 5. **Claim** | Friends | Each friend picks "I am …" (or adds their name), ticks the items they had, and sets **weights** for uneven sharing (weight 2 vs 1 = twice the share). |
| 6. **Pay** | Organizer | Records who actually paid and how much. One or more payers are allowed. |
| 7. **Lock** | Organizer | Freezes the bill and computes each person's share and the **settlement**: who pays whom, and how much. Unlocking is allowed if something changes. |
| 8. **Summary** | Everyone | A per-person breakdown plus a copy-as-text settlement to paste into a group chat. |

### Expected behaviour (the rules)

- **Exact money.** All amounts are stored as integers in the currency's minor unit (sen, cents, whole yen). People's shares always add up to the bill total **exactly**. Property-based tests enforce this.
- **Fair rounding.** Each amount is split by weight using the largest-remainder method: the leftover cents go to the largest fractional parts, and ties go to the participant ID that sorts first. Nobody is off by more than one minor unit, and the same input always gives the same output.
- **Charges follow consumption.** Each bill-level charge (tax, service, voucher) is split in proportion to each person's item subtotal. Negative charges such as vouchers reduce the share in the same proportion.
- **A bill can be locked only when:**
  - every line item has at least one claim,
  - the reconciliation gap is 0,
  - payments add up to the printed total,
  - and item subtotals are positive whenever charges exist.
- **Minimal transfers.** The settlement repeatedly pairs the largest debtor with the largest creditor, so it never needs more than n − 1 transfers.
- **Friends can't tamper.** The share link can only identify, claim and set weights. Editing items, charges, payments and lock state requires the admin link.
- **Retention.** Unlocked drafts are purged after 7 days, and locked bills 30 days after locking, together with their images.
- **Limits.**
  - Uploads: 10 per hour per IP.
  - Model calls: at most 2 per upload.
  - Participants: up to 20 per bill.
  - Supported currencies: MYR, SGD, USD, THB, EUR, GBP, AUD, CAD, CNY, HKD, TWD, IDR, PHP, VND, JPY and KRW.

The full domain glossary is in [`CONTEXT.md`](CONTEXT.md), and the original spec is in [`_docs/plan.md`](_docs/plan.md).

## Quickstart (one command)

Requires Docker.

```bash
docker compose up --build
```

| URL | What |
|---|---|
| http://localhost:8000 | SplitSnap. The **demo extractor** is on by default, so no API key is needed. |
| http://localhost:3000 | Grafana: the SplitSnap dashboard, traces, logs and alerts |

To use real receipt extraction, put `ANTHROPIC_API_KEY=…` and `RECEIPT_EXTRACTOR=anthropic` in a `.env` file before starting.

### Without Docker

```bash
uv sync --group dev
uv run python manage.py migrate
uv run python manage.py runserver      # SQLite + fake extractor
```

## Testing

```bash
uv run pytest                 # everything: unit + integration (single command)
uv run pytest -m unit         # pure logic, no database
uv run pytest -m integration  # Django client + database, including the full user journey
uv run ruff check . && uv run ruff format --check .
```

- **Unit tests** (`tests/unit/`) cover the splitting engine (including Hypothesis property tests), money conversion, receipt schema and validation, image preparation, and the telemetry helpers.
- **Integration tests** (`tests/integration/`) cover the views, models, purge command and health check. They include `test_journey.py`, which walks upload → review → participants → claims → payments → lock → summary and checks that the settlement balances.
- CI runs both suites against PostgreSQL 16, with an 80% coverage gate.

## Architecture

```
Browser (Django templates + HTMX) ──HTTP──► Django 5.2 / gunicorn ──► PostgreSQL 16
                                                 │  ├─► Anthropic vision API (or demo extractor)
                                                 │  └─► OTLP ──► Grafana LGTM (traces · metrics · logs · alerts)
                                                 │                       └─ webhook ─► alert relay ─► On-call agent
bills/ receipts/ splitting/ core/ config/
```

Details are in [`docs/architecture.md`](docs/architecture.md).

## Delivery: CI/CD and environments

| Environment | How it gets deployed | Where |
|---|---|---|
| **dev** | Automatically after CI passes on `main` ([`cd-dev.yml`](.github/workflows/cd-dev.yml)) | Self-hosted runner, `http://localhost:8001`, with the synthetic probe running |
| **prod** | Manually, with approval ([`promote-prod.yml`](.github/workflows/promote-prod.yml)), using the same image as dev | Self-hosted runner, `http://localhost:8002`, plus a public `https://*.trycloudflare.com` URL |

Images go to the GitHub Container Registry (`ghcr.io/wong80/splitsnap:<sha>`). No third-party account is needed. Each prod deploy publishes its public URL in the workflow run summary and on the repository's **Environments → production** page. See [`docs/deployment.md`](docs/deployment.md).

## Observability and on-call

- **Instrumentation:** the receipt journey is instrumented with OpenTelemetry.
  - **Traces:** the HTTP request, image preparation, each extraction attempt, validation and persistence.
  - **Metrics:** extraction outcomes and latency, bills locked, HTTP latency.
  - **Structured JSON logs:** every line carries `trace_id`, so logs, metrics and traces for one request can be correlated.
- **Privacy:** tokens and receipt contents are scrubbed before export.
- **Viewing and alerts:** everything is stored and shown in a self-hosted Grafana LGTM stack. Alert rules fire on user impact: extraction failure ratio and 5xx ratio.
- **On-call:** when an alert fires, the **alert relay** opens an incident issue and wakes the **On-call agent** (Claude Code). The agent reads the traces and logs, writes a regression test, fixes the bug and opens a PR.

See [`docs/observability.md`](docs/observability.md) and [`docs/runbooks/`](docs/runbooks/).

## How the project is run

The project is built by a team of Claude Code agents (Planner, Implementer, QA, Reviewer, On-call) coordinated through [GitHub Issues](https://github.com/wong80/splitsnap/issues) with acceptance criteria.

| Doc | Purpose |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Entry point for agents: commands, guardrails, doc map |
| [`docs/team.md`](docs/team.md) | Agent roles, responsibilities, hand-offs, escalation |
| [`docs/process.md`](docs/process.md) | Issue → PR → CI → dev → prod workflow |
| [`CONTEXT.md`](CONTEXT.md) | Domain glossary |
| [`docs/adr/`](docs/adr/) | Architecture decision records |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` in Docker | `config.settings.dev` or `config.settings.prod` |
| `DJANGO_SECRET_KEY` | – (required in prod) | Django secret key |
| `DATABASE_URL` | – | PostgreSQL connection string |
| `ALLOWED_HOSTS` | – | Comma-separated host names (`.trycloudflare.com` for the tunnel) |
| `HTTPS_ONLY` | `true` | Set to `false` for plain-HTTP local stacks. This disables SSL redirect and secure cookies. |
| `RECEIPT_EXTRACTOR` | `fake` (dev settings) / `demo` (compose) | `anthropic`, `demo` (sample receipt) or `fake` (empty, for tests) |
| `ANTHROPIC_API_KEY` | – | Required when `RECEIPT_EXTRACTOR=anthropic` |
| `RECEIPT_MODEL` | see `receipts/extraction.py` | Anthropic model ID |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | – (telemetry off) | e.g. `http://lgtm:4318` |
| `OTEL_SERVICE_NAME` | `splitsnap` | Service name in telemetry |
| `DEPLOY_ENV` | `local` | `local`, `dev` or `prod`. Sent as `deployment.environment`. |
| `R2_*` | – | Optional Cloudflare R2 / S3 storage for receipt images. Without these, images go to a local volume. |

## Management commands

```bash
uv run python manage.py purge_expired_bills                         # delete expired bills + images
uv run python manage.py eval_receipts                               # extraction eval suite
uv run python manage.py probe_journey --base-url http://localhost:8000   # synthetic end-to-end check
```
