# Runbooks

One runbook per alert. Each alert's `runbook_url` annotation links here, and the On-call agent reads the matching file first.

| Alert | Fires when | Runbook |
|---|---|---|
| `ReceiptExtractionFailing` | More than 20% of extractions end in `error` or `unsupported_currency` over 5 min, sustained for 2 min | [ReceiptExtractionFailing.md](ReceiptExtractionFailing.md) |
| `HighServerErrorRate` | 5xx responses are above 5% of requests over 5 min, sustained for 2 min | [HighServerErrorRate.md](HighServerErrorRate.md) |

## How alerts reach the on-call agent

```
Grafana alert rule (observability/grafana/alerting/)
   └─ webhook contact point "oncall-relay"  (Bearer token)
        └─ ops/alert_relay.py  (on the runner machine, port 9095)
             ├─ gh issue create  → incident issue (type:incident, agent:oncall)
             └─ wakes the On-call agent:
                  --mode local   claude -p … --agent oncall   in worktree incident-<n>
                  --mode github  repository_dispatch → .github/workflows/oncall.yml (self-hosted)
```

Start the relay once on the runner machine:

```bash
python ops/alert_relay.py --mode local          # reads ~/.splitsnap/relay.token
```

## Investigation toolkit (read-only)

`G` is `http://localhost:3030` for dev and prod, or `http://localhost:3000` for local compose.

```bash
# 1. What is failing, and where? Error ratio by route and status
curl -s -G "$G/api/datasources/proxy/uid/prometheus/api/v1/query" --data-urlencode \
 'query=sum by (http_route, http_response_status_code) (rate(http_server_request_duration_seconds_count{http_response_status_code=~"5..", deployment_environment_name="dev"}[5m]))'

# 2. Error logs with trace IDs
curl -s -G "$G/api/datasources/proxy/uid/loki/loki/api/v1/query_range" \
  --data-urlencode 'query={service_name="splitsnap", deployment_environment_name="dev", severity_text="ERROR"}' \
  --data-urlencode 'limit=20'

# 3. Find failing traces, then open one
curl -s -G "$G/api/datasources/proxy/uid/tempo/api/search" \
  --data-urlencode 'q={resource.service.name="splitsnap" && status=error}' --data-urlencode 'limit=10'
curl -s "$G/api/datasources/proxy/uid/tempo/api/traces/<trace_id>"    # exception.type / message / stacktrace

# 4. Extraction outcomes
curl -s -G "$G/api/datasources/proxy/uid/prometheus/api/v1/query" --data-urlencode \
 'query=sum by (outcome) (increase(splitsnap_extraction_total{deployment_environment_name="dev"}[15m]))'
```

## Rules for every incident

- **Fix forward through code.** Agents fix with a PR. A human handles rollbacks (`deploy/deploy.sh <env> --rollback`) and config or secret changes.
- **Evidence in the issue:** trace IDs, span names, exception types and counts. Never include tokens, receipt contents or names.
- **Close the loop:** regression test → fix PR (`Closes #n`) → merge → CD to dev → alert resolves → the relay comments "resolved" → human promotes to prod → postmortem in `docs/incidents/`.

## On-call drill (end to end, locally)

This reproduces a real failure mode, a receipt in a currency SplitSnap doesn't support, and lets the whole chain run: alert → incident issue → agent → fix PR.

```bash
# 1. Relay on the host; it opens issues on GitHub and starts Claude Code locally
python ops/alert_relay.py --mode local --grafana-url http://localhost:3000 --token local-dev-relay-token

# 2. Stack where every upload is an Indian-rupee receipt, with synthetic traffic every 30 s
DEMO_RECEIPT=demo_receipt_inr docker compose --profile probe up --build -d
```

About three minutes later, `HighServerErrorRate` and `ReceiptExtractionFailing` fire. The relay opens an incident and the agent starts working in `~/.splitsnap/worktrees/incident-<n>`; its output goes to `~/.splitsnap/oncall-<n>.log`. Past drills are written up in [`../incidents/`](../incidents/).
