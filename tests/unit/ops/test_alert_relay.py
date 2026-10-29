import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from ops import alert_relay
from ops.alert_relay import Alert, Relay, issue_body, make_handler

FIRING = {
    "status": "firing",
    "fingerprint": "abc123",
    "labels": {
        "alertname": "HighServerErrorRate",
        "deployment_environment_name": "dev",
        "severity": "page",
    },
    "annotations": {
        "summary": "More than 5% of requests fail with 5xx in dev",
        "description": "Users are seeing server errors.",
        "runbook_url": "https://example/docs/runbooks/HighServerErrorRate.md",
    },
    "startsAt": "2026-10-29T14:00:00Z",
    "endsAt": "0001-01-01T00:00:00Z",
    "values": {"A": 0.42, "C": 1},
}


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.spawned = []

    def run(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs.get("input")))
        out = (
            "https://github.com/wong80/splitsnap/issues/42"
            if cmd[:3] == ["gh", "issue", "create"]
            else ""
        )
        return SimpleNamespace(stdout=out, returncode=0)

    def spawn(self, cmd, **kwargs):
        self.spawned.append((cmd, kwargs["cwd"]))
        return SimpleNamespace(pid=1)


@pytest.fixture
def relay_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(alert_relay, "STATE_HOME", tmp_path)

    def make(mode):
        runner = FakeRunner()
        relay = Relay(
            repo="wong80/splitsnap",
            mode=mode,
            repo_dir=tmp_path,
            grafana_url="http://g:3030",
            base_branch="main",
            state_file=tmp_path / "incidents.json",
            run=runner.run,
            spawn=runner.spawn,
        )
        return relay, runner

    return make


def test_firing_alert_opens_one_incident_and_wakes_local_agent(relay_factory):
    relay, runner = relay_factory("local")
    actions = relay.handle({"alerts": [FIRING]})
    assert actions[0] == "opened #42 for HighServerErrorRate/dev"

    create = next(c for c in runner.calls if c[0][:3] == ["gh", "issue", "create"])
    assert "type:incident,agent:oncall" in create[0]
    assert "docs/runbooks/HighServerErrorRate.md" in create[1]

    cmd, cwd = runner.spawned[0]
    assert cmd[0] == "claude" and "--agent" in cmd and "oncall" in cmd
    assert "Incident issue: #42" in cmd[2]
    assert cwd.name == "incident-42"
    assert any(c[0][:2] == ["git", "-C"] and "worktree" in c[0] for c in runner.calls)

    # Grafana repeats notifications; the same fingerprint must not open a second incident.
    assert relay.handle({"alerts": [FIRING]}) == []


def test_resolved_alert_comments_and_clears_state(relay_factory):
    relay, runner = relay_factory("issue-only")
    relay.handle({"alerts": [FIRING]})
    actions = relay.handle(
        {"alerts": [{**FIRING, "status": "resolved", "endsAt": "2026-10-29T14:30:00Z"}]}
    )
    assert actions == ["resolved #42"]
    comment = runner.calls[-1][0]
    assert comment[:3] == ["gh", "issue", "comment"] and "42" in comment
    assert json.loads((relay.state_file).read_text()) == {}


def test_github_mode_dispatches_oncall_workflow(relay_factory):
    relay, runner = relay_factory("github")
    relay.handle({"alerts": [FIRING]})
    cmd, stdin = runner.calls[-1]
    assert cmd[:3] == ["gh", "api", "repos/wong80/splitsnap/dispatches"]
    payload = json.loads(stdin)
    assert payload["event_type"] == "oncall-alert"
    assert payload["client_payload"]["issue"] == 42
    assert not runner.spawned


def test_issue_body_has_acceptance_criteria_and_no_raw_payload():
    body = issue_body(Alert.from_grafana(FIRING), "http://g:3030")
    assert "### Acceptance criteria" in body
    assert "A=0.420" in body
    assert "http://g:3030/d/splitsnap?var-env=dev" in body


def test_http_endpoint_requires_bearer_token(relay_factory):
    relay, _ = relay_factory("issue-only")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(relay, "s3cret"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/alert"
    body = json.dumps({"alerts": [FIRING]}).encode()
    try:
        bad = urllib.request.Request(url, data=body, headers={"Authorization": "Bearer nope"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(bad, timeout=5)
        assert exc.value.code == 401

        good = urllib.request.Request(url, data=body, headers={"Authorization": "Bearer s3cret"})
        with urllib.request.urlopen(good, timeout=5) as resp:
            assert json.load(resp)["actions"][0].startswith("opened #42")
    finally:
        server.shutdown()


def test_wake_issue_starts_agent_for_existing_incident(monkeypatch, tmp_path):
    monkeypatch.setattr(alert_relay, "STATE_HOME", tmp_path)
    runner = FakeRunner()
    real_relay = Relay

    def fake_relay(**kwargs):
        return real_relay(**kwargs, run=runner.run, spawn=runner.spawn)

    monkeypatch.setattr(alert_relay, "Relay", fake_relay)
    alert_relay.main(["--wake-issue", "31", "--alert", "HighServerErrorRate", "--env", "local"])
    cmd, cwd = runner.spawned[0]
    assert "Incident issue: #31" in cmd[2]
    assert cwd.name == "incident-31"
