import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tokencat_native.cli import app
from conftest import PRIVATE_BODY, PRIVATE_ID, claude_row, write_rows

runner = CliRunner()


def arguments(home):
    return ["--home", str(home), "--since", "2026-10-02", "--until", "2026-10-02", "--timezone", "UTC"]


def test_candidate_json_uses_native_contract_and_anonymous_ids(all_sources):
    result = runner.invoke(app, [*arguments(all_sources), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["candidate_version"] == "0.9.0rc1"
    assert payload["dashboard"]["schema_version"] == 1
    assert payload["dashboard"]["summary"]["event_count"] == 4
    assert payload["query"]["granularity"] == "day"
    assert PRIVATE_BODY not in result.stdout and PRIVATE_ID not in result.stdout
    assert (all_sources / ".tokencat-candidate/usage.sqlite3").exists()
    assert not (all_sources / ".tokencat").exists()
    assert not (all_sources / "Library/Application Support/TokenCat").exists()


def test_default_view_and_dashboard_subcommand_preserve_recent_session_choice(source_home):
    default = runner.invoke(app, arguments(source_home))
    assert default.exit_code == 0, default.output
    assert "native candidate" in default.stdout
    assert "Daily usage" in default.stdout
    assert "Recent sessions" not in default.stdout
    recent = runner.invoke(app, ["dashboard", *arguments(source_home), "--theme", "light"])
    assert recent.exit_code == 0, recent.output
    assert "Recent sessions" in recent.stdout
    assert PRIVATE_ID not in recent.stdout and PRIVATE_BODY not in recent.stdout


@pytest.mark.parametrize("flags,heading", [(["--weekly"], "Weekly usage"), (["--monthly"], "Monthly usage")])
def test_calendar_views_render_native_details(source_home, flags, heading):
    result = runner.invoke(app, [*arguments(source_home), *flags])
    assert result.exit_code == 0, result.output
    assert heading in result.stdout


@pytest.mark.parametrize("flags", [
    ["--provider", "gemini"], ["--provider", "copilot"], ["--lan"], ["sessions"],
    ["--daily", "--weekly"], ["--timezone", "invalid-zone"], ["--since", "bad-time"],
    ["--since", "2026-10-04"], ["--no-price", "--json"],
])
def test_unsupported_or_invalid_arguments_fail_before_creating_ledger(source_home, flags):
    result = runner.invoke(app, [*arguments(source_home), *flags])
    assert result.exit_code == 2, result.output
    assert not (source_home / ".tokencat-candidate").exists()


def test_bad_custom_catalog_is_an_error_instead_of_builtin_fallback(source_home, tmp_path):
    catalog = tmp_path / "invalid.json"
    catalog.write_text("{}")
    result = runner.invoke(app, [*arguments(source_home), "--pricing-path", str(catalog)])
    assert result.exit_code == 1
    assert "Candidate error:" in result.stderr
    assert not (source_home / ".tokencat-candidate/usage.sqlite3").exists()


def test_candidate_does_not_read_or_rewrite_legacy_price_cache(source_home):
    path = source_home / ".tokencat/pricing/catalog.json"
    path.parent.mkdir(parents=True)
    path.write_text("LEGACY_CACHE_SENTINEL")
    result = runner.invoke(app, [*arguments(source_home), "--json"])
    assert result.exit_code == 0, result.output
    assert path.read_text() == "LEGACY_CACHE_SENTINEL"
    assert json.loads(result.stdout)["dashboard"]["summary"]["cost"]["priced_tokens"] == 1050


def test_unknown_models_remain_unpriced_and_no_price_hides_cost_columns(source_home):
    row = claude_row()
    row["message"]["model"] = "private-model"
    write_rows(source_home, f".claude/projects/example/{PRIVATE_ID}.jsonl", [row])
    normal = runner.invoke(app, arguments(source_home))
    assert normal.exit_code == 0, normal.output
    assert "No price record" in normal.stdout
    hidden = runner.invoke(app, [*arguments(source_home), "--no-price"])
    assert hidden.exit_code == 0, hidden.output
    assert "Estimated cost" not in hidden.stdout and "Est cost" not in hidden.stdout
    assert "Prices:" not in hidden.stdout


def test_real_console_entrypoint_and_module_are_candidate_only(source_home):
    command = Path(sys.executable).with_name("tokencat-candidate")
    for prefix in ([str(command)], [sys.executable, "-m", "tokencat_native"]):
        result = subprocess.run([*prefix, *arguments(source_home), "--json"], text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["dashboard"]["summary"]["cost"]["total_tokens"] == 1050


def test_candidate_version_needs_no_native_engine():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "TokenCat native candidate 0.9.0rc1"
