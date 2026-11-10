# Deployment

SplitSnap is delivered with **no third-party sign-up or free trial**. Everything runs on GitHub, which the project already uses, plus one machine with Docker:

| Piece | Provided by | Why |
|---|---|---|
| CI | GitHub Actions (hosted runners) | Lint, unit and integration tests, container smoke test |
| Image registry | GitHub Container Registry, `ghcr.io/wong80/splitsnap` | Built once per commit; the same image goes to dev and then prod |
| Deploy target | GitHub Actions **self-hosted runner** + Docker Compose | Two isolated stacks on the runner machine |
| Approval gate | GitHub **Environments** (`dev`, `production` with a required reviewer) | Production promotion is manual and approved |
| Public HTTPS URL | Cloudflare **quick tunnel** (`cloudflared --url`, no account) | Gives prod a public `https://<random>.trycloudflare.com` address |
| Telemetry and alerts | Self-hosted Grafana LGTM (`deploy/compose.ops.yaml`) | See [observability.md](observability.md) |

## Environments

| | dev | prod |
|---|---|---|
| Compose project | `splitsnap-dev` | `splitsnap-prod` |
| Local URL | http://localhost:8001 | http://localhost:8002 |
| Public URL | – | `https://<random>.trycloudflare.com`. Shown in the workflow summary and on *Environments → production*. |
| Deployed by | [`cd-dev.yml`](../.github/workflows/cd-dev.yml), automatically after CI passes on `main` | [`promote-prod.yml`](../.github/workflows/promote-prod.yml), started manually and approved by a reviewer |
| Extractor | `demo` | `demo` by default. Set `RECEIPT_EXTRACTOR=anthropic` and `ANTHROPIC_API_KEY` in the runner environment to use the real model. |
| Synthetic traffic | `probe` service runs the journey every 60 s | – |
| Settings | [`deploy/env/dev.env`](../deploy/env/dev.env) | [`deploy/env/prod.env`](../deploy/env/prod.env) |
| Database | Postgres 16, volume `splitsnap-dev_pgdata` | Postgres 16, volume `splitsnap-prod_pgdata` |

Secrets (`DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`) are generated on first deploy into `~/.splitsnap/<env>.secrets` on the runner machine. They never enter the repository or GitHub.

## Pipeline

```
push to main ─► CI (lint · unit · integration · container probe)
                 │ success
                 ▼
            cd-dev.yml
              build  (GitHub-hosted): docker build → ghcr.io/wong80/splitsnap:<sha>, :dev
              deploy-dev (self-hosted): deploy/deploy.sh dev ghcr.io/…:<sha>
                                         └─ healthz + journey probe; auto-restore previous image on failure
                 │
   human: Actions → "Promote to production" → Run workflow (sha) 
                 ▼
            promote-prod.yml
              verify (GitHub-hosted): <sha> must have a successful `dev` deployment
              promote (self-hosted, environment: production → waits for reviewer approval)
                         deploy/deploy.sh prod ghcr.io/…:<sha>  (same image as dev)
                         └─ healthz + journey probe through the public tunnel URL
                         tag :prod
```

## Common operations

```bash
# Deploy by hand (what the workflows run)
deploy/deploy.sh dev  ghcr.io/wong80/splitsnap:<sha>
deploy/deploy.sh prod ghcr.io/wong80/splitsnap:<sha>
PUBLIC_TUNNEL=0 deploy/deploy.sh prod <image>      # prod without the public tunnel

# Roll back to the previously deployed image
deploy/deploy.sh prod --rollback
# …or re-run "Promote to production" with an older SHA

# Inspect
docker compose -p splitsnap-prod -f deploy/compose.deploy.yaml --env-file deploy/env/prod.env ps
docker compose -p splitsnap-prod -f deploy/compose.deploy.yaml --env-file deploy/env/prod.env logs tunnel | grep trycloudflare
cat ~/.splitsnap/prod.history                       # timestamp, image, public URL
```

## First-time setup

1. **Runner:** run `./deploy/runner/setup-runner.ps1`, then `run.cmd`. See [`deploy/runner/README.md`](../deploy/runner/README.md).
2. **Environments:** `dev` and `production` already exist. `production` requires approval from `wong80`.
3. **Registry:** nothing to set up. The workflows authenticate to GHCR with the built-in `GITHUB_TOKEN`.
4. Merge to `main` to trigger the first dev deploy.

## Limitations (trade-offs of the no-sign-up approach)

- **Availability depends on the runner machine.** If it is off or asleep, dev and prod are unreachable and deploys queue.
- **The quick-tunnel URL changes** whenever the `tunnel` container restarts. Cloudflare also documents quick tunnels as being for testing, with no uptime guarantee. The current URL is always in the latest promote run and in `~/.splitsnap/prod.history`.
- **dev and prod share one machine.** They are isolated by compose project, network, volumes and ports, but not by hardware.
- Moving to a managed host later only requires replacing `deploy/deploy.sh`. The image, the workflows' build and verify jobs, and the environments stay the same.
