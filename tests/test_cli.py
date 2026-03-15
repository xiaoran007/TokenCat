from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tokencat.cli import app

from conftest import create_codex_state_db, write_json, write_jsonl


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
