import json
import subprocess
import sys
from pathlib import Path

import pytest
from rich.text import Text
from typer import rich_utils
from typer.testing import CliRunner

import tokencat.cli as shared_cli
from tokencat.cli import app
from conftest import PRIVATE_BODY, PRIVATE_ID, claude_row, write_rows

runner = CliRunner()


def arguments():
    return ["--since", "2026-10-02", "--until", "2026-10-02"]


@pytest.mark.parametrize("colored", [False, True])
def test_cli_has_only_local_dashboard_command(monkeypatch, colored):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(rich_utils, "FORCE_TERMINAL", colored)
    monkeypatch.setattr(rich_utils, "COLOR_SYSTEM", "standard" if colored else None)
    assert app.registered_callback.callback is shared_cli.main
    assert app.registered_commands[0].callback is shared_cli.dashboard
    assert len(app.registered_commands) == 1 and app.registered_groups == []
    result = runner.invoke(app, ["dashboard", "--help"], color=colored)
    assert result.exit_code == 0
    assert ("\x1b[" in result.stdout) == colored
    help_text = Text.from_ansi(result.stdout).plain
    assert "--weekly" in help_text and "--theme" in help_text
    assert "gemini" not in help_text and "copilot" not in help_text


def test_cli_json_reuses_shared_format_and_anonymous_sessions(all_sources):
    result = runner.invoke(app, [*arguments(), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload) == {"generated_at", "filters", "providers", "summary", "warnings"}
    overview = payload["summary"]["overview"]
    assert overview["session_count"] == 4
    assert {row["provider"] for row in payload["providers"]} == {"codex", "claude", "opencode", "antigravity"}
    assert overview["token_totals"]["output"] + overview["token_totals"]["reasoning"] == 220
    for private in (PRIVATE_BODY, PRIVATE_ID, "/PRIVATE_PROJECT"):
        assert private not in result.stdout
    assert all(row["anon_session_id"].startswith("session:") for row in payload["summary"]["recent_sessions"])
    assert payload["summary"]["pricing"]["catalog"]["model_count"] is None
    assert payload["summary"]["pricing"]["coverage"]["unattributed_token_count"] is None
    assert (all_sources / ".tokencat/usage.sqlite3").exists()
    assert not (all_sources / ".tokencat-candidate").exists()
    assert not (all_sources / "Library/Application Support/TokenCat").exists()


def test_cli_uses_original_renderer_with_native_data(source_home, monkeypatch):
    captured = []
    monkeypatch.setattr(shared_cli, "render_dashboard", lambda *args, **kwargs: captured.append(kwargs))
    result = runner.invoke(app, arguments())
    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    assert captured[0]["overview"]["token_totals"]["total"] == 1050
    assert captured[0]["daily"][0].token_totals.total == 1050


def test_default_and_dashboard_preserve_recent_session_choice(source_home):
    default = runner.invoke(app, arguments())
    assert default.exit_code == 0, default.output
    assert "local usage cockpit" in default.stdout and "Daily Usage" in default.stdout
    assert "Recent Sessions" not in default.stdout
    recent = runner.invoke(app, ["dashboard", *arguments(), "--theme", "light"])
    assert recent.exit_code == 0, recent.output
    assert "Recent Sessions" in recent.stdout
    assert PRIVATE_ID not in recent.stdout and PRIVATE_BODY not in recent.stdout


@pytest.mark.parametrize("flags,heading", [(["--weekly"], "Weekly Usage"), (["--monthly"], "Monthly Usage")])
def test_calendar_views_render_with_shared_dashboard(source_home, flags, heading):
    result = runner.invoke(app, [*arguments(), *flags])
    assert result.exit_code == 0, result.output
    assert heading in result.stdout
    exported = runner.invoke(app, [*arguments(), *flags, "--json"])
    assert json.loads(exported.stdout)["summary"]["daily"][0]["date"] == "2026-10-02"


@pytest.mark.parametrize("flags", [
    ["--provider", "gemini"], ["--provider", "copilot"], ["--lan"], ["sessions"],
    ["--daily", "--weekly"], ["--since", "bad-time"], ["--since", "2026-10-04"],
])
def test_unsupported_or_invalid_arguments_fail_before_creating_ledger(source_home, flags):
    result = runner.invoke(app, [*arguments(), *flags])
    assert result.exit_code == 2, result.output
    assert not (source_home / ".tokencat").exists()


def test_cli_does_not_read_or_rewrite_legacy_price_cache(source_home):
    path = source_home / ".tokencat/pricing/catalog.json"
    path.parent.mkdir(parents=True)
    path.write_text("LEGACY_CACHE_SENTINEL")
    result = runner.invoke(app, [*arguments(), "--json"])
    assert result.exit_code == 0, result.output
    assert path.read_text() == "LEGACY_CACHE_SENTINEL"
    assert json.loads(result.stdout)["summary"]["pricing"]["coverage"]["priced_tokens"] == 1050


def test_unknown_prices_and_no_price_follow_shared_upper_layer(source_home):
    row = claude_row()
    row["message"]["model"] = "private-model"
    write_rows(source_home, f".claude/projects/example/{PRIVATE_ID}.jsonl", [row])
    normal = runner.invoke(app, arguments())
    assert normal.exit_code == 0, normal.output
    assert "No price record" in normal.stdout
    exported = runner.invoke(app, [*arguments(), "--no-price", "--json"])
    assert exported.exit_code == 0, exported.output
    payload = json.loads(exported.stdout)
    assert payload["summary"]["pricing"] == {"catalog": None, "coverage": None}
    assert payload["summary"]["overview"]["estimated_cost"]["total_cost"] == 0
    assert payload["summary"]["overview"]["token_totals"]["total"] == 1050


def test_real_console_entrypoint_and_module_use_shared_frontend(source_home):
    command = Path(sys.executable).with_name("tokencat")
    for prefix in ([str(command)], [sys.executable, "-m", "tokencat"]):
        result = subprocess.run([*prefix, *arguments(), "--json"], text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["summary"]["overview"]["token_totals"]["total"] == 1050


def test_cli_json_skips_update_check(source_home, monkeypatch):
    def fail_check(version):
        raise AssertionError("JSON export must not check for updates")
    monkeypatch.setattr(shared_cli, "check_latest_version", fail_check)
    result = runner.invoke(app, [*arguments(), "--json"])
    assert result.exit_code == 0, result.output


def test_removed_python_core_and_remote_modules_are_not_importable():
    from importlib.util import find_spec
    for module in ("tokencat.providers", "tokencat.node", "tokencat.pricing",
                   "tokencat.core.aggregate", "tokencat.core.filters", "tokencat.core.pricing"):
        assert find_spec(module) is None, module
