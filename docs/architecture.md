# Architecture

SplitSnap is a server-rendered Django application. The browser is the frontend. It renders Django templates and uses [HTMX](https://htmx.org) to send form posts and partial requests to the backend. All state lives in PostgreSQL.

## Runtime view

```
┌────────────── Browser (frontend) ──────────────┐
│ Django templates + HTMX                        │
│  • organizer: /b/<admin_token>/                │
│  • friend:    /s/<share_token>/                │
└───────────────┬────────────────────────────────┘
                │ HTTP (form POST / hx-post / hx-get)
┌───────────────▼─────────────── Django 5.2 (backend, gunicorn) ─────────────────────┐
│ core/        healthz, request middleware, telemetry bootstrap, journey probe        │
│ bills/       views (upload, admin, share, summary), models, purge command           │
│ receipts/    image prep (Pillow, EXIF strip) → extractor → validation + 1 retry     │
│ splitting/   pure Python: money (minor units), allocation, settlement               │
└───────┬───────────────────────┬──────────────────────────┬──────────────────────────┘
        │ psycopg               │ HTTPS                    │ OTLP (traces, metrics, logs)
┌───────▼───────┐   ┌───────────▼──────────┐   ┌───────────▼────────────────────────┐
│ PostgreSQL 16 │   │ Anthropic Messages   │   │ Grafana LGTM (OTel Collector,      │
│ (bills, items,│   │ API (vision) — or    │   │ Tempo, Loki, Prometheus, Grafana)  │
│ claims, ...)  │   │ the demo extractor   │   │ dashboards + alert rules           │
└───────────────┘   └──────────────────────┘   └──────────────┬─────────────────────┘
                                                              │ webhook on alert
                                                   ┌──────────▼───────────┐
                                                   │ ops/alert_relay.py   │──► GitHub incident issue
                                                   │                      │──► On-call agent (Claude Code)
                                                   └──────────────────────┘
```

## Frontend ↔ backend contract

The UI is server-rendered: every interaction is an HTTP request to a Django view, and the view returns HTML. The admin and share views dispatch on the `action` form field.

| Route | Methods | Who | Purpose |
|---|---|---|---|
| `/` | GET, POST | organizer | Upload form; POST runs extraction and creates the bill (rate-limited to 10/hour per IP) |
| `/b/<admin_token>/` | GET, POST | organizer | Review and edit items and charges, manage participants and payments, confirm, lock and unlock. Actions: `update_bill`, `add_item`, `delete_item`, `add_charge`, `delete_charge`, `add_participant`, `remove_participant`, `add_payment`, `delete_payment`, `confirm`, `lock`, `unlock` |
| `/s/<share_token>/` | GET, POST | friend | Identify yourself (`identify`), then `toggle_claim` and `set_weight` |
| `/s/<share_token>/summary` | GET | friend | Settlement summary for a locked bill |
| `/healthz` | GET | ops | Database round-trip check used by Docker, CD and the probe |

## Bill lifecycle

```
upload ──► review ──confirm──► open ──lock──► locked
              ▲                  │  ▲           │
              └──────(edit)──────┘  └──unlock───┘
```

- **review**: the organizer fixes extraction mistakes until the reconciliation gap is 0.
- **open**: friends claim items, and the organizer records payments.
- **locked**: the allocation and settlement are frozen in `SplitSnapshot` and `Transfer` rows.

The lock preconditions and every domain term are defined in [`CONTEXT.md`](../CONTEXT.md).

## Module boundaries

| Package | May import | Must not import |
|---|---|---|
| `splitting/` | stdlib only | Django, `bills`, `receipts` |
| `receipts/` | `splitting`, pydantic, Pillow, anthropic | `bills` |
| `bills/` | everything above | – |
| `core/` | Django, OpenTelemetry | `bills` (except the journey probe, which talks HTTP) |

## Configuration

| Setting module | Used by | Database | Receipt extractor | Storage |
|---|---|---|---|---|
| `config.settings.dev` | `runserver`, pytest | SQLite, or `DATABASE_URL` if set | `fake` | local `media/` |
| `config.settings.prod` | Docker image (local compose, dev, prod) | `DATABASE_URL` (Postgres) | `RECEIPT_EXTRACTOR` (`demo` by default in compose) | local volume, or R2 when `R2_BUCKET_NAME` is set |

All environment variables are listed in the [README](../README.md#configuration).

## Key decisions

- **Money is integer minor units**, using ISO 4217 exponents. Allocation uses the largest-remainder method with ties broken by participant ID, so the parts always sum exactly to the total.
- **Settlement is greedy**, pairing the largest debtor with the largest creditor. This needs at most n − 1 transfers.
- **There are no accounts.** Access uses 256-bit admin and share tokens. Tokens are scrubbed from logs and telemetry.
- **Extraction is synchronous**, with at most 2 model calls per upload (the second is a retry with gap feedback).
- **Self-hosted delivery**: Docker Compose stacks on a GitHub self-hosted runner, images in GHCR and a Cloudflare quick tunnel. No third-party sign-up is needed. See [`deployment.md`](deployment.md).
- Architecture decision records live in [`adr/`](adr/).
