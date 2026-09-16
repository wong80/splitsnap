# SplitSnap

Snap a receipt, split the bill. Upload a receipt photo and SplitSnap extracts line items using AI, lets friends claim what they ordered, and computes fair settlements with minimal transfers.

## Architecture

```
Django 5.2  ─►  Anthropic Vision API (receipt extraction)
    │
    ├── bills/       Domain models, views, templates
    ├── receipts/    Image prep, extraction, validation
    ├── splitting/   Pure-Python engine (allocation, settlement)
    ├── core/        Health check, middleware
    └── config/      Settings (base/dev/prod), URLs
```

**Key design decisions:**

- **Minor-unit integer arithmetic** — all money stored as integers (cents/sen), never floats. ISO 4217 exponents for currency conversion.
- **Largest-remainder allocation** — splits totals fairly with deterministic tie-breaking by participant ID.
- **Greedy matching settlement** — guarantees ≤ n−1 transfers to settle all balances.
- **Token-based access** — 256-bit hex tokens for admin/share URLs. No user accounts needed.
- **Synchronous extraction** — one blocking request per upload (max 2 LLM calls with retry). Keeps the stack simple; no task queue.

## Setup

```bash
# Clone and install
git clone <repo-url> && cd splitsnap
uv sync

# Run migrations
uv run python manage.py migrate

# Start dev server
uv run python manage.py runserver
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DJANGO_SECRET_KEY` | prod | Secret key for Django |
| `DJANGO_SETTINGS_MODULE` | yes | `config.settings.dev` or `config.settings.prod` |
| `DATABASE_URL` | prod | PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | yes | Anthropic API key for receipt extraction |
| `RECEIPT_EXTRACTOR` | no | `anthropic` (default) or `fake` for tests |
| `RECEIPT_MODEL` | no | Anthropic model ID (default in extraction.py) |
| `SENTRY_DSN` | no | Sentry DSN for error tracking |
| `R2_ACCESS_KEY_ID` | prod | Cloudflare R2 access key |
| `R2_SECRET_ACCESS_KEY` | prod | Cloudflare R2 secret key |
| `R2_BUCKET_NAME` | prod | R2 bucket name |
| `R2_ENDPOINT_URL` | prod | R2 S3-compatible endpoint |

## Commands

```bash
uv run python manage.py purge_expired_bills   # Delete expired bills + images
uv run python manage.py eval_receipts          # Run extraction eval suite
```

## Testing

```bash
uv run python -m pytest -q          # Run all tests
uv run ruff check .                  # Lint
uv run ruff format --check .         # Format check
```

## Deployment

Configured for [Render](https://render.com) via `render.yaml`. Includes web service, PostgreSQL, and daily cron job for bill purging.
