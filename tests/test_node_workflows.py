from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tokencat.core.models import ScanFilters, ScanResult
from tokencat.cli import app
from tokencat.node.client import NodeEndpoint
from tokencat.node.identity import NodeIdentity
from tokencat.node.process import NodeProcessStatus, start_detached_node
from tokencat.node.ssh import build_ssh_snapshot_command
from tokencat.node.ssh_config import SSHHostCandidate, load_ssh_host_candidates
from tokencat.node.client import RemoteScan
from tokencat.node.trust import TrustedNode


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
    monkeypatch.setattr("tokencat.cli.load_ssh_host_candidates", lambda: [])
    monkeypatch.setattr("tokencat.cli.load_trusted_nodes", lambda: [])
    monkeypatch.setattr("tokencat.cli.select_nodes_checkbox", lambda nodes, trusted_ids: nodes)
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


def test_ssh_config_candidates_parse_common_host_block(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_text(
        """
Host dl-pt280-cu128
    HostName 192.168.8.215
    Port 2222
    User dev
    IdentityFile ~/.ssh/id_ed25519

Host *
    User ignored
""",
        encoding="utf-8",
    )

    candidates = load_ssh_host_candidates(config)

    assert candidates == [
        SSHHostCandidate(
            alias="dl-pt280-cu128",
            hostname="192.168.8.215",
            user="dev",
            port="2222",
            identity_file="~/.ssh/id_ed25519",
        )
    ]
    assert candidates[0].address == "dev@192.168.8.215:2222"


def test_ssh_snapshot_command_uses_host_alias_and_filter_args() -> None:
    filters = ScanFilters(providers=set(), since=None, until=None)

    command = build_ssh_snapshot_command("dl-pt280-cu128", filters)

    assert command[:4] == ["ssh", "-o", "BatchMode=yes", "dl-pt280-cu128"]
    assert command[4] == 'if [ -n "$SHELL" ]; then exec "$SHELL" -lc \'tokencat snapshot --json\'; else exec sh -c \'tokencat snapshot --json\'; fi'


def test_nodes_trust_can_select_ssh_config_candidate(monkeypatch) -> None:
    candidate = SSHHostCandidate(alias="dl-pt280-cu128", hostname="192.168.8.215", user="dev", port="2222")
    remote = RemoteScan(
        endpoint=NodeEndpoint(
            node_id="remote-node",
            name="dl-pt280-cu128",
            base_url="ssh://dl-pt280-cu128",
            auth="ssh",
        ),
        node=NodeIdentity("remote-node", "dl-pt280-cu128", "0.0.0"),
        result=ScanResult(statuses=[], sessions=[]),
    )
    saved: dict[str, object] = {}

    monkeypatch.setattr("tokencat.cli.load_or_create_identity", lambda: NodeIdentity("local", "Local", "0.0.0"))
    monkeypatch.setattr("tokencat.cli.discover_nodes", lambda timeout: [])
    monkeypatch.setattr("tokencat.cli.load_ssh_host_candidates", lambda: [candidate])
    monkeypatch.setattr("tokencat.cli.load_trusted_nodes", lambda: [])
    monkeypatch.setattr("tokencat.cli.select_nodes_checkbox", lambda nodes, trusted_ids: nodes)
    monkeypatch.setattr("tokencat.cli.fetch_ssh_snapshot", lambda ssh_host, filters, timeout: remote)
    monkeypatch.setattr("tokencat.cli.Confirm.ask", lambda *args, **kwargs: True)

    def fake_save(nodes):
        saved["nodes"] = nodes

    monkeypatch.setattr("tokencat.cli.save_trusted_nodes", fake_save)

    result = CliRunner().invoke(app, ["nodes", "--trust", "--timeout", "0.5"])

    assert result.exit_code == 0
    trusted = saved["nodes"]
    assert len(trusted) == 1
    assert trusted[0].transport == "ssh"
    assert trusted[0].ssh_host == "dl-pt280-cu128"


def test_nodes_remove_deletes_selected_trusted_nodes(monkeypatch) -> None:
    trusted_nodes = [
        TrustedNode(
            node_id="node-1",
            name="Air",
            transport="http",
            base_url="http://air.local:8765",
            token_env="TOKENCAT_NODE_TOKEN",
        ),
        TrustedNode(
            node_id="node-2",
            name="Studio",
            transport="ssh",
            ssh_host="studio",
        ),
    ]
    saved: dict[str, object] = {}

    monkeypatch.setattr("tokencat.cli.load_or_create_identity", lambda: NodeIdentity("local", "Local", "0.0.0"))
    monkeypatch.setattr("tokencat.cli.load_trusted_nodes", lambda: trusted_nodes)
    monkeypatch.setattr("tokencat.cli.select_nodes_checkbox", lambda nodes, trusted_ids, **kwargs: [nodes[0]])
    monkeypatch.setattr("tokencat.cli.Confirm.ask", lambda *args, **kwargs: True)

    def fake_save(nodes):
        saved["nodes"] = nodes

    monkeypatch.setattr("tokencat.cli.save_trusted_nodes", fake_save)

    result = CliRunner().invoke(app, ["nodes", "--remove"])

    assert result.exit_code == 0
    assert "Removed 1 node(s)." in result.stdout
    remaining = saved["nodes"]
    assert len(remaining) == 1
    assert remaining[0].node_id == "node-2"
