from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tokencat.cli import app

from conftest import create_codex_state_db, write_copilot_cli_session_state, write_json, write_jsonl


def write_copilot_session_json(
    home: Path,
    workspace_id: str,
    session_id: str,
    payload: dict[str, object],
) -> Path:
    path = (
        home
        / "Library"
        / "Application Support"
        / "Code"
        / "User"
        / "workspaceStorage"
        / workspace_id
        / "chatSessions"
        / f"{session_id}.json"
    )
    write_json(path, payload)
    return path


def seed_bootstrap_marker(home: Path) -> None:
    write_json(
        home / ".tokencat" / "pricing" / "bootstrap.json",
        {"attempted_at": "2026-03-16T00:00:00+00:00", "succeeded": False},
    )


def test_sessions_json_redacts_title_and_path_by_default(sample_home: Path, monkeypatch) -> None:
    codex_dir = sample_home / ".codex"
    write_jsonl(
        codex_dir / "archived_sessions" / "rollout-2026-03-15T16-07-41-019cf23f-a38c-7c21-b2f2-ecbb145c1652.jsonl",
        [
            {
                "timestamp": "2026-03-15T16:07:41.000Z",
                "type": "session_meta",
                "payload": {
                    "id": "019cf23f-a38c-7c21-b2f2-ecbb145c1652",
                    "timestamp": "2026-03-15T16:07:41.000Z",
                    "cwd": "/repo/project",
                    "source": "vscode",
                    "model_provider": "openai",
                    "cli_version": "0.115.0-alpha.4",
                },
            },
            {
                "timestamp": "2026-03-15T16:08:00.000Z",
                "type": "turn_context",
                "payload": {"turn_id": "turn-1", "model": "gpt-5-codex"},
            },
            {
                "timestamp": "2026-03-15T16:08:02.000Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {
                            "input_tokens": 120,
                            "cached_input_tokens": 20,
                            "output_tokens": 30,
                            "reasoning_output_tokens": 10,
                            "total_tokens": 180,
                        }
                    },
                },
            },
        ],
    )
    write_jsonl(
        codex_dir / "session_index.jsonl",
        [{"id": "019cf23f-a38c-7c21-b2f2-ecbb145c1652", "thread_name": "Sensitive Title"}],
    )
    create_codex_state_db(
        codex_dir / "state_5.sqlite",
        [
            (
                "019cf23f-a38c-7c21-b2f2-ecbb145c1652",
                1773590861,
                1773590961,
                "vscode",
                "openai",
                "/repo/project",
                "Sensitive Title",
                180,
                "0.115.0-alpha.4",
            )
        ],
    )
    write_json(
        sample_home / ".gemini" / "settings.json",
        {"model": {"name": "gemini-3.1-pro-preview"}},
    )

    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)
    runner = CliRunner()

    result = runner.invoke(app, ["sessions", "--provider", "codex", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["items"][0]["anon_session_id"]
    assert "provider_session_id" not in payload["items"][0]
    assert "title" not in payload["items"][0]
    assert "cwd" not in payload["items"][0]
    assert "source_refs" not in payload["items"][0]

    reveal = runner.invoke(app, ["sessions", "--provider", "codex", "--show-title", "--show-path", "--json"])
    assert reveal.exit_code == 0
    revealed_payload = json.loads(reveal.stdout)
    assert revealed_payload["items"][0]["provider_session_id"] == "019cf23f-a38c-7c21-b2f2-ecbb145c1652"
    assert revealed_payload["items"][0]["title"] == "Sensitive Title"
    assert revealed_payload["items"][0]["cwd"] == "/repo/project"


def test_doctor_and_models_commands_report_provider_status_and_model_usage(sample_home: Path, monkeypatch) -> None:
    seed_bootstrap_marker(sample_home)
    write_json(
        sample_home / ".gemini" / "settings.json",
        {"model": {"name": "gemini-3.1-pro-preview"}},
    )
    write_json(
        sample_home / ".gemini" / "tmp" / "temp" / "chats" / "session-2026-02-23T00-04-19b8af10.json",
        {
            "sessionId": "19b8af10-5307-4b43-a9c3-97cecb7ebbfd",
            "startTime": "2026-02-23T00:07:11.272Z",
            "lastUpdated": "2026-02-23T00:07:39.001Z",
            "projectHash": "project-hash",
            "messages": [
                {
                    "timestamp": "2026-02-23T00:07:39.001Z",
                    "model": "gemini-3-pro-preview",
                    "tokens": {"input": 10, "output": 5, "cached": 1, "thoughts": 0, "tool": 0, "total": 16},
                }
            ],
        },
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)
    runner = CliRunner()

    doctor_result = runner.invoke(app, ["doctor", "--json"])
    assert doctor_result.exit_code == 0
    doctor_payload = json.loads(doctor_result.stdout)
    statuses = {item["provider"]: item["status"] for item in doctor_payload["providers"]}
    assert statuses["gemini"] == "supported"
    assert statuses["copilot"] == "not_found"

    models_result = runner.invoke(app, ["models", "--provider", "gemini", "--since", "30d", "--json"])
    assert models_result.exit_code == 0
    models_payload = json.loads(models_result.stdout)
    assert models_payload["items"][0]["model"] == "gemini-3-pro-preview"
    assert models_payload["items"][0]["token_totals"]["total"] == 16

    doctor_text = runner.invoke(app, ["doctor"])
    assert doctor_text.exit_code == 0
    assert "Gemini CLI" in doctor_text.stdout
    assert "GitHub Copilot" in doctor_text.stdout


def test_terminal_ui_hides_broken_zero_token_sessions_but_json_keeps_them(sample_home: Path, monkeypatch) -> None:
    seed_bootstrap_marker(sample_home)
    codex_dir = sample_home / ".codex"
    write_jsonl(
        codex_dir / "session_index.jsonl",
        [
            {"id": "valid-session", "thread_name": "SQLite Only Session"},
            {"id": "broken-session", "thread_name": "Broken Empty Session"},
        ],
    )
    create_codex_state_db(
        codex_dir / "state_5.sqlite",
        [
            (
                "valid-session",
                1773590000,
                1773590600,
                "vscode",
                "openai",
                "/repo/other",
                "SQLite Only Session",
                640,
                "0.115.0-alpha.4",
            ),
            (
                "broken-session",
                1773591000,
                1773591001,
                "vscode",
                "openai",
                "/repo/broken",
                "Broken Empty Session",
                0,
                "0.115.0-alpha.4",
            ),
        ],
    )

    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)
    runner = CliRunner()

    ui_result = runner.invoke(app, ["sessions", "--provider", "codex", "--show-title", "--no-price"])
    assert ui_result.exit_code == 0
    assert "SQLite" in ui_result.stdout
    assert "Broken" not in ui_result.stdout
    assert "Codex" in ui_result.stdout

    json_result = runner.invoke(app, ["sessions", "--provider", "codex", "--show-title", "--json"])
    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    titles = {item["title"] for item in payload["items"]}
    assert titles == {"SQLite Only Session", "Broken Empty Session"}

    models_result = runner.invoke(app, ["models", "--provider", "codex", "--no-price"])
    assert models_result.exit_code == 0
    assert "No model usage in this window." in models_result.stdout


def test_copilot_doctor_sessions_and_models_commands_report_vscode_usage(sample_home: Path, monkeypatch) -> None:
    seed_bootstrap_marker(sample_home)
    write_copilot_session_json(
        sample_home,
        "workspace-a",
        "session-a",
        {
            "sessionId": "session-a",
            "creationDate": 1771433087111,
            "customTitle": "Copilot Pairing",
            "requests": [
                {
                    "timestamp": 1771433108061,
                    "modelId": "copilot/gpt-5.3-codex",
                    "result": {"usage": {"promptTokens": 24438, "completionTokens": 238}},
                }
            ],
        },
    )

    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)
    runner = CliRunner()

    doctor_result = runner.invoke(app, ["doctor", "--json"])
    assert doctor_result.exit_code == 0
    doctor_payload = json.loads(doctor_result.stdout)
    statuses = {item["provider"]: item["status"] for item in doctor_payload["providers"]}
    assert statuses["copilot"] == "supported"

    sessions_result = runner.invoke(app, ["sessions", "--provider", "copilot", "--since", "365d", "--json"])
    assert sessions_result.exit_code == 0
    sessions_payload = json.loads(sessions_result.stdout)
    assert len(sessions_payload["items"]) == 1
    assert sessions_payload["items"][0]["primary_model"] == "copilot/gpt-5.3-codex"
    assert sessions_payload["items"][0]["token_totals"]["total"] == 24676
    assert "provider_session_id" not in sessions_payload["items"][0]

    models_result = runner.invoke(app, ["models", "--provider", "copilot", "--since", "365d", "--json", "--no-price"])
    assert models_result.exit_code == 0
    models_payload = json.loads(models_result.stdout)
    assert models_payload["items"][0]["model"] == "copilot/gpt-5.3-codex"
    assert models_payload["items"][0]["token_totals"]["total"] == 24676


def test_copilot_doctor_sessions_and_models_commands_report_cli_session_state_usage(sample_home: Path, monkeypatch) -> None:
    seed_bootstrap_marker(sample_home)
    write_copilot_cli_session_state(
        sample_home,
        "cf76050a-de21-4ea4-84d4-15393a6791d9",
        [
            {
                "timestamp": "2026-03-16T21:58:06.501Z",
                "type": "session.start",
                "data": {
                    "sessionId": "cf76050a-de21-4ea4-84d4-15393a6791d9",
                    "startTime": "2026-03-16T21:58:06.501Z",
                },
            },
            {
                "timestamp": "2026-03-16T22:08:06.501Z",
                "type": "session.shutdown",
                "data": {
                    "sessionStartTime": "2026-03-16T21:58:06.501Z",
                    "currentModel": "claude-sonnet-4.6",
                    "totalPremiumRequests": 1,
                    "modelMetrics": {
                        "claude-sonnet-4.6": {
                            "usage": {
                                "inputTokens": 428306,
                                "outputTokens": 8235,
                                "cacheReadTokens": 406292,
                                "cacheWriteTokens": 0,
                            },
                            "requests": {"count": 16, "cost": 1},
                        }
                    },
                },
            },
        ],
        workspace={
            "id": "cf76050a-de21-4ea4-84d4-15393a6791d9",
            "cwd": "/repo/copilot-playground",
            "created_at": "2026-03-16T21:58:06.501Z",
            "updated_at": "2026-03-16T22:01:33.596Z",
        },
    )

    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)
    runner = CliRunner()

    doctor_result = runner.invoke(app, ["doctor", "--json"])
    assert doctor_result.exit_code == 0
    doctor_payload = json.loads(doctor_result.stdout)
    statuses = {item["provider"]: item["status"] for item in doctor_payload["providers"]}
    assert statuses["copilot"] == "supported"

    sessions_result = runner.invoke(app, ["sessions", "--provider", "copilot", "--since", "365d", "--json"])
    assert sessions_result.exit_code == 0
    sessions_payload = json.loads(sessions_result.stdout)
    assert len(sessions_payload["items"]) == 1
    assert sessions_payload["items"][0]["primary_model"] == "claude-sonnet-4.6"
    assert sessions_payload["items"][0]["token_totals"]["input"] == 428306
    assert sessions_payload["items"][0]["token_totals"]["cached"] == 406292
    assert sessions_payload["items"][0]["token_totals"]["total"] == 436541
    assert "provider_session_id" not in sessions_payload["items"][0]

    models_result = runner.invoke(app, ["models", "--provider", "copilot", "--since", "365d", "--json", "--no-price"])
    assert models_result.exit_code == 0
    models_payload = json.loads(models_result.stdout)
    assert models_payload["items"][0]["model"] == "claude-sonnet-4.6"
    assert models_payload["items"][0]["token_totals"]["cached"] == 406292
