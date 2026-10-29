"""Alert relay: Grafana webhook -> GitHub incident issue -> On-call agent (Claude Code).

Runs on the runner machine, next to the Grafana ops stack:

    python ops/alert_relay.py --mode local              # wake Claude Code on this machine
    python ops/alert_relay.py --mode github             # trigger .github/workflows/oncall.yml
    python ops/alert_relay.py --mode issue-only         # just open/close incident issues

For every *firing* alert (deduplicated by Grafana fingerprint) it:
  1. opens a `type:incident` issue with the alert details and runbook link, and
  2. wakes the On-call agent (.claude/agents/oncall.md) with the incident context.
When the alert *resolves*, it comments on the incident issue.

Only the Python standard library is used, so it runs with any Python 3.10+.
Never put customer data in issues: alert labels/values are aggregate metrics only.
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger("alert_relay")

STATE_HOME = Path(os.environ.get("SPLITSNAP_HOME", Path.home() / ".splitsnap"))
ONCALL_TOOLS = [
    "Read",
    "Edit",
    "Write",
    "Grep",
    "Glob",
    "Bash(git:*)",
    "Bash(gh:*)",
    "Bash(uv:*)",
    "Bash(curl:*)",
    "Bash(python:*)",
    "Bash(ls:*)",
    "Bash(cat:*)",
    "Bash(mkdir:*)",
]


@dataclass
class Alert:
    name: str
    status: str
    fingerprint: str
    environment: str
    summary: str
    description: str
    runbook_url: str
    starts_at: str
    ends_at: str
    values: dict
    generator_url: str = ""
    labels: dict = field(default_factory=dict)

    @classmethod
    def from_grafana(cls, raw: dict) -> Alert:
        labels = raw.get("labels") or {}
        ann = raw.get("annotations") or {}
        return cls(
            name=labels.get("alertname", "unknown"),
            status=raw.get("status", "firing"),
            fingerprint=raw.get("fingerprint")
            or f"{labels.get('alertname')}:{labels.get('deployment_environment_name')}",
            environment=labels.get("deployment_environment_name", "unknown"),
            summary=ann.get("summary", ""),
            description=ann.get("description", ""),
            runbook_url=ann.get("runbook_url", ""),
            starts_at=raw.get("startsAt", ""),
            ends_at=raw.get("endsAt", ""),
            values=raw.get("values") or {},
            generator_url=raw.get("generatorURL", ""),
            labels=labels,
        )

    @property
    def runbook_path(self) -> str:
        return f"docs/runbooks/{self.name}.md"


def issue_title(alert: Alert) -> str:
    return f"[incident][{alert.environment}] {alert.name}: {alert.summary}"[:250]


def issue_body(alert: Alert, grafana_url: str) -> str:
    values = (
        ", ".join(
            f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in alert.values.items()
        )
        or "n/a"
    )
    labels = "\n".join(f"| `{k}` | `{v}` |" for k, v in sorted(alert.labels.items()))
    return f"""### Alert
{alert.name}

### Impact
{alert.description}

| | |
|---|---|
| Environment | `{alert.environment}` |
| Started (UTC) | {alert.starts_at} |
| Values | {values} |
| Runbook | [{alert.runbook_path}]({alert.runbook_url or alert.runbook_path}) |
| Dashboard | {grafana_url}/d/splitsnap?var-env={alert.environment} |

<details><summary>Alert labels</summary>

| label | value |
|---|---|
{labels}

</details>

### Acceptance criteria
- [ ] Root cause identified with trace/log evidence
- [ ] Regression test added
- [ ] Fix merged and deployed to dev; alert resolved
- [ ] Postmortem written in docs/incidents/

_Opened automatically by `ops/alert_relay.py`. The On-call agent has been woken up._
"""


def oncall_prompt(alert: Alert, issue: int, grafana_url: str, base_branch: str) -> str:
    return f"""You are the SplitSnap On-call agent. Follow .claude/agents/oncall.md exactly.

Incident issue: #{issue}
Alert: {alert.name} ({alert.environment}), started {alert.starts_at}
Summary: {alert.summary}
Current values: {json.dumps(alert.values)}
Runbook: {alert.runbook_path}
Grafana (read-only queries via the datasource proxy, see docs/observability.md): {grafana_url}

You are in a fresh git worktree on branch `incident-{issue}`, created from `{base_branch}`.
Open your fix PR against `{base_branch}` with `Closes #{issue}` in the body.
Do not merge, do not deploy, do not touch production. Stop after the PR is open and the
incident issue has your summary comment."""


class Relay:
    def __init__(
        self,
        *,
        repo: str,
        mode: str,
        repo_dir: Path,
        grafana_url: str,
        base_branch: str = "main",
        budget_usd: float = 5.0,
        state_file: Path | None = None,
        run=subprocess.run,
        spawn=subprocess.Popen,
    ) -> None:
        self.repo = repo
        self.mode = mode
        self.repo_dir = repo_dir
        self.grafana_url = grafana_url.rstrip("/")
        self.base_branch = base_branch
        self.budget_usd = budget_usd
        self.state_file = state_file or STATE_HOME / "incidents.json"
        self._run = run
        self._spawn = spawn
        self._lock = threading.Lock()

    # --- state: fingerprint -> incident issue number ---
    def _load(self) -> dict[str, int]:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, state: dict[str, int]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _gh(self, *args: str, stdin: str | None = None) -> str:
        result = self._run(
            ["gh", *args],
            input=stdin,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        return result.stdout.strip()

    # --- webhook handling ---
    def handle(self, payload: dict) -> list[str]:
        actions = []
        with self._lock:
            state = self._load()
            for raw in payload.get("alerts", []):
                alert = Alert.from_grafana(raw)
                if alert.status == "firing" and alert.fingerprint not in state:
                    issue = self._open_incident(alert)
                    state[alert.fingerprint] = issue
                    self._save(state)
                    actions.append(f"opened #{issue} for {alert.name}/{alert.environment}")
                    actions.append(self._wake_agent(alert, issue))
                elif alert.status == "resolved" and alert.fingerprint in state:
                    issue = state.pop(alert.fingerprint)
                    self._save(state)
                    self._gh(
                        "issue",
                        "comment",
                        str(issue),
                        "-R",
                        self.repo,
                        "-b",
                        f"✅ **Alert resolved**: `{alert.name}` in `{alert.environment}` "
                        f"stopped firing at {alert.ends_at} (alert relay).",
                    )
                    actions.append(f"resolved #{issue}")
        return actions

    def _open_incident(self, alert: Alert) -> int:
        url = self._gh(
            "issue",
            "create",
            "-R",
            self.repo,
            "--title",
            issue_title(alert),
            "--label",
            "type:incident,agent:oncall",
            "--body-file",
            "-",
            stdin=issue_body(alert, self.grafana_url),
        )
        return int(url.rstrip("/").rsplit("/", 1)[-1])

    def _wake_agent(self, alert: Alert, issue: int) -> str:
        if self.mode == "issue-only":
            return "agent not started (issue-only mode)"
        if self.mode == "github":
            payload = json.dumps(
                {
                    "event_type": "oncall-alert",
                    "client_payload": {
                        "issue": issue,
                        "alert": alert.name,
                        "environment": alert.environment,
                        "summary": alert.summary,
                        "starts_at": alert.starts_at,
                        "values": alert.values,
                        "base_branch": self.base_branch,
                    },
                }
            )
            self._gh("api", f"repos/{self.repo}/dispatches", "--input", "-", stdin=payload)
            return f"dispatched oncall.yml for #{issue}"
        return self._start_local_agent(alert, issue)

    def _start_local_agent(self, alert: Alert, issue: int) -> str:
        worktree = STATE_HOME / "worktrees" / f"incident-{issue}"
        self._run(["git", "-C", str(self.repo_dir), "fetch", "-q", "origin"], check=True)
        self._run(
            [
                "git",
                "-C",
                str(self.repo_dir),
                "worktree",
                "add",
                "-B",
                f"incident-{issue}",
                str(worktree),
                f"origin/{self.base_branch}",
            ],
            check=True,
            capture_output=True,
        )
        log_path = STATE_HOME / f"oncall-{issue}.log"
        cmd = [
            "claude",
            "-p",
            oncall_prompt(alert, issue, self.grafana_url, self.base_branch),
            "--agent",
            "oncall",
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            *ONCALL_TOOLS,
            "--max-budget-usd",
            str(self.budget_usd),
            "--output-format",
            "text",
        ]
        log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 - owned by the child
        self._spawn(
            cmd, cwd=worktree, stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL
        )
        self._gh(
            "issue",
            "comment",
            str(issue),
            "-R",
            self.repo,
            "-b",
            f"🤖 **On-call agent woken** on the runner machine (Claude Code, `--agent oncall`, "
            f"budget ${self.budget_usd:.0f}) in worktree branch `incident-{issue}`.",
        )
        return f"started on-call agent for #{issue} (log: {log_path})"


def make_handler(relay: Relay, token: str):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            self._reply(200 if self.path == "/healthz" else 404, {"status": "ok"})

        def do_POST(self):  # noqa: N802
            if self.path != "/alert":
                return self._reply(404, {"error": "not found"})
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if token and not hmac.compare_digest(supplied, token):
                return self._reply(401, {"error": "bad token"})
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
                actions = relay.handle(payload)
            except Exception as exc:  # report to Grafana so it retries
                log.exception("alert handling failed")
                return self._reply(500, {"error": type(exc).__name__})
            for action in actions:
                log.info(action)
            return self._reply(200, {"actions": actions})

        def log_message(self, fmt, *args):
            log.debug(fmt, *args)

    return Handler


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--mode", choices=["local", "github", "issue-only"], default="local")
    parser.add_argument("--port", type=int, default=9095)
    # Loopback only: Docker Desktop forwards host.docker.internal to the host loopback.
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--repo", default="wong80/splitsnap")
    parser.add_argument("--repo-dir", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument(
        "--grafana-url", default=os.environ.get("GRAFANA_URL", "http://localhost:3030")
    )
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--budget-usd", type=float, default=5.0)
    parser.add_argument("--token", default=os.environ.get("ALERT_RELAY_TOKEN"))
    wake = parser.add_argument_group("wake the agent for an existing incident, then exit")
    wake.add_argument("--wake-issue", type=int, help="incident issue number")
    wake.add_argument("--alert", help="alert name, e.g. HighServerErrorRate")
    wake.add_argument("--env", default="dev", help="deployment environment label")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s alert_relay %(message)s")
    relay = Relay(
        repo=args.repo,
        mode=args.mode,
        repo_dir=args.repo_dir,
        grafana_url=args.grafana_url,
        base_branch=args.base_branch,
        budget_usd=args.budget_usd,
    )

    if args.wake_issue:
        if not args.alert:
            parser.error("--wake-issue requires --alert")
        alert = Alert.from_grafana(
            {"labels": {"alertname": args.alert, "deployment_environment_name": args.env}}
        )
        log.info(relay._wake_agent(alert, args.wake_issue))
        return

    token = args.token
    if token is None and (STATE_HOME / "relay.token").exists():
        token = (STATE_HOME / "relay.token").read_text(encoding="utf-8").strip()
    if not token:
        sys.exit("No relay token: use --token, ALERT_RELAY_TOKEN or ~/.splitsnap/relay.token")

    server = ThreadingHTTPServer((args.host, args.port), make_handler(relay, token))
    log.info("listening on %s:%s (mode=%s, repo=%s)", args.host, args.port, args.mode, args.repo)
    server.serve_forever()


if __name__ == "__main__":
    main()
