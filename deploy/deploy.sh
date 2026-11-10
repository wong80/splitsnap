#!/usr/bin/env bash
# Deploy one SplitSnap environment on this machine (the self-hosted runner).
#
#   deploy/deploy.sh <dev|prod> <image>        e.g. ghcr.io/wong80/splitsnap:3f2c1ab
#   deploy/deploy.sh <dev|prod> --rollback     redeploy the previous image from history
#
# Each environment is its own compose project (splitsnap-dev / splitsnap-prod) with its own
# Postgres volume. Secrets are generated once per environment and kept outside the repo in
# $SPLITSNAP_HOME (default ~/.splitsnap). After `up`, a smoke test runs the journey probe.
# If the smoke test fails, the previous image is restored automatically.
set -euo pipefail

ENVIRONMENT="${1:?usage: deploy.sh <dev|prod> <image|--rollback>}"
TARGET="${2:?usage: deploy.sh <dev|prod> <image|--rollback>}"
case "$ENVIRONMENT" in dev|prod) ;; *) echo "unknown environment: $ENVIRONMENT" >&2; exit 2;; esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="${SPLITSNAP_HOME:-$HOME/.splitsnap}"
PROJECT="splitsnap-$ENVIRONMENT"
ENV_FILE="$ROOT/deploy/env/$ENVIRONMENT.env"
HISTORY="$STATE/$ENVIRONMENT.history"
mkdir -p "$STATE"

log() { printf '[deploy:%s] %s\n' "$ENVIRONMENT" "$*"; }

# --- secrets (generated once, never committed) ---
SECRETS="$STATE/$ENVIRONMENT.secrets"
if [[ ! -f "$SECRETS" ]]; then
  log "generating secrets in $SECRETS"
  rand() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$1"; }
  umask 077
  printf 'DJANGO_SECRET_KEY=%s\nPOSTGRES_PASSWORD=%s\n' "$(rand 50)" "$(rand 32)" > "$SECRETS"
fi
set -a
# shellcheck disable=SC1090
source "$SECRETS"
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# PUBLIC_TUNNEL=0 deploys prod without the public tunnel (local-only verification).
# Without TLS in front, the app must accept plain HTTP.
if [[ "$ENVIRONMENT" == prod && "${PUBLIC_TUNNEL:-1}" == "0" ]]; then
  export COMPOSE_PROFILES="" HTTPS_ONLY=false
fi

# --- resolve image ---
if [[ "$TARGET" == "--rollback" ]]; then
  IMAGE="$(tail -n 2 "$HISTORY" 2>/dev/null | head -n 1 | cut -f2)"
  [[ -n "$IMAGE" ]] || { echo "no previous deployment to roll back to" >&2; exit 1; }
  log "rolling back to $IMAGE"
else
  IMAGE="$TARGET"
fi
PREVIOUS="$(tail -n 1 "$HISTORY" 2>/dev/null | cut -f2 || true)"
export IMAGE

compose() {
  docker compose -p "$PROJECT" --env-file "$ENV_FILE" -f "$ROOT/deploy/compose.deploy.yaml" "$@"
}

# --- shared ops stack (telemetry + alerting) ---
docker network inspect splitsnap-ops >/dev/null 2>&1 || docker network create splitsnap-ops >/dev/null
if [[ -f "$ROOT/deploy/compose.ops.yaml" ]]; then
  # Shared secret between Grafana's webhook and ops/alert_relay.py (which reads the same file).
  if [[ ! -f "$STATE/relay.token" ]]; then
    (umask 077; head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 40 > "$STATE/relay.token")
  fi
  export ALERT_RELAY_TOKEN
  ALERT_RELAY_TOKEN="$(cat "$STATE/relay.token")"
  log "ensuring ops stack (Grafana LGTM) is up"
  docker compose -p splitsnap-ops -f "$ROOT/deploy/compose.ops.yaml" up -d --wait --wait-timeout 180
fi

# --- deploy ---
if [[ "$IMAGE" == ghcr.io/* ]]; then
  log "pulling $IMAGE"
  docker pull -q "$IMAGE" >/dev/null
fi
log "starting $PROJECT with $IMAGE"
compose up -d --remove-orphans --wait --wait-timeout 180

# --- smoke test ---
public_url=""
smoke() {
  curl -fsS "http://127.0.0.1:$WEB_PORT/healthz" >/dev/null || return 1
  local base="http://localhost:8000"
  if [[ "$ENVIRONMENT" == prod && "${PUBLIC_TUNNEL:-1}" != "0" ]]; then
    for _ in $(seq 1 30); do
      public_url="$(compose logs tunnel 2>/dev/null | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -n 1 || true)"
      [[ -n "$public_url" ]] && break
      sleep 2
    done
    [[ -n "$public_url" ]] || { log "tunnel URL not found"; return 1; }
    base="$public_url"
    log "public URL: $public_url"
  fi
  # The tunnel's DNS name can take a few seconds to resolve; retry the journey probe.
  for attempt in 1 2 3 4 5 6; do
    if compose exec -T web python manage.py probe_journey --base-url "$base" --timeout 60; then
      return 0
    fi
    log "probe attempt $attempt failed; retrying"
    sleep 5
  done
  return 1
}

if ! smoke; then
  log "SMOKE TEST FAILED for $IMAGE"
  if [[ -n "$PREVIOUS" && "$PREVIOUS" != "$IMAGE" ]]; then
    log "restoring previous image $PREVIOUS"
    IMAGE="$PREVIOUS" compose up -d --remove-orphans --wait --wait-timeout 180 || true
  fi
  exit 1
fi

printf '%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$IMAGE" "$public_url" >> "$HISTORY"
log "deployed $IMAGE"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "public_url=${public_url:-http://localhost:$WEB_PORT}" >> "$GITHUB_OUTPUT"
fi
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "### Deployed \`$ENVIRONMENT\`"
    echo ""
    echo "| | |"
    echo "|---|---|"
    echo "| Image | \`$IMAGE\` |"
    echo "| Local URL | http://localhost:$WEB_PORT |"
    [[ -n "$public_url" ]] && echo "| **Public URL** | $public_url |"
    echo "| Smoke test | journey probe passed |"
  } >> "$GITHUB_STEP_SUMMARY"
fi
