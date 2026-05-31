from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tokencat.cli import app
from tokencat.node.client import NodeEndpoint
from tokencat.node.identity import NodeIdentity
from tokencat.node.process import NodeProcessStatus, start_detached_node


def test_start_detached_node_writes_pid_and_uses_foreground_child(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    class FakeProcess:
        pid = 4242

    def fake_popen(command, **kwargs):
        calls.append(command)
        assert kwargs["stdin"] is not None
        assert kwargs["stdout"] is not None
        assert kwargs["stderr"] is not None
        assert kwargs["start_new_session"] is True
        return FakeProcess()

    monkeypatch.setattr("tokencat.node.process.subprocess.Popen", fake_popen)
    monkeypatch.setattr("tokencat.node.process._pid_is_running", lambda pid: False)

    pid_path = tmp_path / "node.pid"
    log_path = tmp_path / "logs" / "node.log"
    status = start_detached_node(["--lan", "--port", "9876"], pid_path=pid_path, log_path=log_path)

    assert status.running is True
    assert status.pid == 4242
    assert pid_path.read_text(encoding="utf-8").strip() == "4242"
    assert calls
    assert calls[0][1:5] == ["-m", "tokencat", "serve", "--foreground"]
    assert "--lan" in calls[0]


def test_serve_defaults_to_detached_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_start(args):
        captured["args"] = args
        return NodeProcessStatus(pid=1234, running=True, pid_path=Path("/tmp/node.pid"), log_path=Path("/tmp/node.log"))

    monkeypatch.setattr("tokencat.cli.start_detached_node", fake_start)

    result = CliRunner().invoke(app, ["serve", "--lan", "--port", "9876"])

    assert result.exit_code == 0
    assert "background" in result.stdout
    assert captured["args"] == ["--host", "127.0.0.1", "--port", "9876", "--token-env", "TOKENCAT_NODE_TOKEN", "--lan"]


def test_nodes_trust_uses_checkbox_selection(monkeypatch) -> None:
    endpoint = NodeEndpoint(
        node_id="node-1",
        name="Air",
        base_url="http://air.local:8765",
        auth="token",
    )
    saved: dict[str, object] = {}

    monkeypatch.setattr("tokencat.cli.load_or_create_identity", lambda: NodeIdentity("local", "Local", "0.0.0"))
    monkeypatch.setattr("tokencat.cli.discover_nodes", lambda timeout: [endpoint])
    monkeypatch.setattr("tokencat.cli.load_trusted_nodes", lambda: [])
    monkeypatch.setattr("tokencat.cli.select_nodes_checkbox", lambda nodes, trusted_ids: [endpoint])
    monkeypatch.setattr("tokencat.cli.Prompt.ask", lambda *args, **kwargs: "TOKENCAT_NODE_TOKEN")
    monkeypatch.setattr("tokencat.cli.Confirm.ask", lambda *args, **kwargs: True)

    def fake_save(nodes):
        saved["nodes"] = nodes

    monkeypatch.setattr("tokencat.cli.save_trusted_nodes", fake_save)

    result = CliRunner().invoke(app, ["nodes", "--trust", "--timeout", "0.5"])

    assert result.exit_code == 0
    assert "Trusted 1 node(s)." in result.stdout
    trusted = saved["nodes"]
    assert len(trusted) == 1
    assert trusted[0].node_id == "node-1"
    assert trusted[0].token_env == "TOKENCAT_NODE_TOKEN"
