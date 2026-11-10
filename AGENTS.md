# AGENTS.md

Read this first. It is the entry point for every agent (and human) working on SplitSnap. Keep it short: details live in the linked docs.

## What this is

SplitSnap is a receipt bill splitter. An organizer uploads a receipt photo, a vision LLM extracts the line items, friends claim what they ate through a share link, and the app computes exactly who owes whom in the currency's minor units. It is built with Django 5.2, templates and HTMX, and PostgreSQL. It is delivered as Docker images to self-hosted dev and prod stacks.

## Commands

```bash
docker compose up --build            # full stack: app :8000, Postgres, Grafana :3000
uv sync --group dev                  # local Python env
uv run pytest                        # all tests (unit + integration)
uv run pytest -m unit                # fast, no database
uv run pytest -m integration         # Django client + database, incl. full journey
uv run ruff check . && uv run ruff format --check .
uv run python manage.py runserver    # without Docker (SQLite, fake extractor)
uv run python manage.py probe_journey --base-url http://localhost:8000
```

## Guardrails (non-negotiable)

1. **Money is an integer in minor units.** Never use floats. Convert only through `splitting.money` (`to_minor`, `to_display`). The allocated parts must sum exactly to the whole.
2. **`splitting/` is pure Python.** It must not import Django.
3. **Privacy.** Never put admin or share tokens, receipt images, item descriptions, participant names or per-person amounts into logs, traces, metrics, issues or PRs. Trace IDs, counts and outcomes are fine.
4. **Use the domain language** from [`CONTEXT.md`](CONTEXT.md): Bill, Line Item, Bill Charge, Participant, Claim, Weight, Lock, Settlement.
5. **Every change starts from a GitHub issue with acceptance criteria** and lands through a PR that says `Closes #N`. Never push to `main`. Only humans approve production.
6. **Tests come first.** Pure logic goes in `tests/unit/`. Anything that touches the database or HTTP goes in `tests/integration/`.

## Doc map

| Need | Read |
|---|---|
| Domain terms and rules | [`CONTEXT.md`](CONTEXT.md) |
| Components, routes, module boundaries | [`docs/architecture.md`](docs/architecture.md) |
| Who does what (agent roles) | [`docs/team.md`](docs/team.md) and [`.claude/agents/`](.claude/agents/) |
| How work flows (issue → PR → CI → dev → prod) | [`docs/process.md`](docs/process.md) |
| Environments, CD, rollback | [`docs/deployment.md`](docs/deployment.md) |
| Telemetry, dashboards, alerts | [`docs/observability.md`](docs/observability.md) |
| What to do when an alert fires | [`docs/runbooks/`](docs/runbooks/) |
| Past incidents | [`docs/incidents/`](docs/incidents/) |
| Why things are the way they are | [`docs/adr/`](docs/adr/) |
| Original product spec | [`_docs/plan.md`](_docs/plan.md), [`_docs/grilling-amendments.md`](_docs/grilling-amendments.md) |
| Task tracker | [GitHub Issues](https://github.com/wong80/splitsnap/issues) |

## Code map

```
bills/       models, views (upload/admin/share/summary), purge command
receipts/    image prep, extractors (anthropic | demo | fake), validation + retry
splitting/   money.py, engine.py (allocation), settle.py (transfers)
core/        healthz, middleware, telemetry.py, probe_journey command
config/      settings (base | dev | prod), urls
deploy/      compose files and scripts for the dev/prod/ops stacks
ops/         alert relay (Grafana webhook → incident issue → on-call agent)
tests/       unit/ and integration/
```
