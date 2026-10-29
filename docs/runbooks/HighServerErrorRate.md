# HighServerErrorRate

**Meaning:** more than 5% of HTTP requests in an environment returned 5xx over the last 5 minutes, sustained for 2 minutes. Users are seeing the error page.

**Severity:** page. The dashboard is *SplitSnap - receipt journey*, in the HTTP (RED) row.

## Triage (5 minutes)

1. **Which routes?** Run query 1 in the [toolkit](README.md#investigation-toolkit-read-only).
   - `""` (upload) points to the extraction or persistence path.
   - `b/<str:admin_token>/` points to the organizer page, usually `_bill_context` or a handler.
   - `s/<str:share_token>/` points to the friend page or a claim handler.
2. **Did it start with a deploy?** Compare the alert start time with `~/.splitsnap/<env>.history` and the latest `CD dev` run. If a deploy caused it, a human may run `deploy/deploy.sh <env> --rollback` while the fix is prepared.
3. **What is the exception?** Run query 3 to find `status=error` traces. In the server span, read the `exception` event (`exception.type`, `exception.message`, `exception.stacktrace`). Use query 2 to see the matching `django.request` ERROR log; it has the same `trace_id`.
4. **Is the database healthy?** Check `curl localhost:<port>/healthz` and `docker compose -p splitsnap-<env> ps`.

## Common causes

| Symptom in the trace | Likely cause | Fix |
|---|---|---|
| `ValueError: Unsupported currency` from `splitting.money.exponent` | A Bill was stored with a currency outside the whitelist and later rendered | Validate the currency where the Bill is created (plan decision D14: block until the organizer picks a supported one) |
| `OperationalError` in psycopg spans | Database down or out of connections | Check the `db` container; this is an infra problem, so escalate to a human |
| `KeyError` / `TypeError` in `bills.views` | Code bug in a handler | Write a regression test and fix |

## Done when

The 5xx ratio is back under 5%, the alert resolves (the relay comments on the issue), and the fix PR includes a regression test.
