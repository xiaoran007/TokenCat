from __future__ import annotations

import json
from pathlib import Path

from tokencat.core.models import ScanFilters
from tokencat.providers.codex import CodexAdapter
from tokencat.providers.copilot import CopilotAdapter
from tokencat.providers.gemini import GeminiAdapter

from conftest import create_codex_state_db, write_json, write_jsonl


def test_codex_adapter_aggregates_archived_sessions_and_sqlite_fallback(sample_home: Path) -> None:
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
        [
            {"id": "019cf23f-a38c-7c21-b2f2-ecbb145c1652", "thread_name": "Build TokenCat"},
            {"id": "fallback-session", "thread_name": "SQLite Only Session"},
        ],
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
                "Build TokenCat",
                180,
                "0.115.0-alpha.4",
            ),
            (
                "fallback-session",
                1773590000,
                1773590600,
                "vscode",
                "openai",
                "/repo/other",
                "SQLite Only Session",
                640,
                "0.115.0-alpha.4",
            ),
        ],
    )

    adapter = CodexAdapter(home=sample_home)
    sessions = {record.provider_session_id: record for record in adapter.scan(ScanFilters())}

    archived = sessions["019cf23f-a38c-7c21-b2f2-ecbb145c1652"]
    assert archived.title == "Build TokenCat"
    assert archived.token_totals.total == 180
    assert archived.primary_model == "gpt-5-codex"
    assert archived.model_usage["gpt-5-codex"].tokens.input == 120

    fallback = sessions["fallback-session"]
    assert fallback.token_totals.total == 640
    assert fallback.title == "SQLite Only Session"
    assert fallback.primary_model is None
    assert fallback.attribution_status == "unattributed"


def test_codex_adapter_reads_active_sessions_before_sqlite_fallback(sample_home: Path) -> None:
    codex_dir = sample_home / ".codex"
    write_jsonl(
        codex_dir / "sessions" / "2026" / "03" / "15" / "rollout-2026-03-15T16-07-41-019cf23f-a38c-7c21-b2f2-ecbb145c1652.jsonl",
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
                "payload": {"turn_id": "turn-1", "model": "gpt-5.4"},
            },
            {
                "timestamp": "2026-03-15T16:08:02.000Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 20,
                            "output_tokens": 30,
                            "reasoning_output_tokens": 10,
                            "total_tokens": 130,
                        }
                    },
                },
            },
            {
                "timestamp": "2026-03-15T16:08:12.000Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 160,
                            "cached_input_tokens": 40,
                            "output_tokens": 45,
                            "reasoning_output_tokens": 12,
                            "total_tokens": 205,
                        }
                    },
                },
            },
        ],
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
                "Build TokenCat",
                99999,
                "0.115.0-alpha.4",
            ),
        ],
    )

    adapter = CodexAdapter(home=sample_home)
    sessions = adapter.scan(ScanFilters())
    assert len(sessions) == 1

    record = sessions[0]
    assert record.primary_model == "gpt-5.4"
    assert record.token_totals.total == 205
    assert record.model_usage["gpt-5.4"].tokens.total == 205
    assert record.attribution_status == "exact"


def test_gemini_adapter_aggregates_message_level_tokens(sample_home: Path) -> None:
    gemini_dir = sample_home / ".gemini"
    write_json(
        gemini_dir / "settings.json",
        {"model": {"name": "gemini-3.1-pro-preview"}},
    )
    write_json(
        gemini_dir / "tmp" / "temp" / "chats" / "session-2026-02-23T00-04-19b8af10.json",
        {
            "sessionId": "19b8af10-5307-4b43-a9c3-97cecb7ebbfd",
            "startTime": "2026-02-23T00:07:11.272Z",
            "lastUpdated": "2026-02-23T00:07:39.001Z",
            "projectHash": "project-hash",
            "messages": [
                {"timestamp": "2026-02-23T00:07:12.000Z", "role": "user"},
                {
                    "timestamp": "2026-02-23T00:07:16.863Z",
                    "model": "gemini-3-pro-preview",
                    "tokens": {"input": 5140, "output": 59, "cached": 2671, "thoughts": 174, "tool": 0, "total": 5373},
                },
                {
                    "timestamp": "2026-02-23T00:07:39.001Z",
                    "model": "gemini-3-pro-preview",
                    "tokens": {"input": 10328, "output": 1058, "cached": 3307, "thoughts": 923, "tool": 0, "total": 12309},
                },
            ],
        },
    )

    adapter = GeminiAdapter(home=sample_home)
    sessions = adapter.scan(ScanFilters())
    assert len(sessions) == 1
    record = sessions[0]
    assert record.primary_model == "gemini-3-pro-preview"
    assert record.token_totals.total == 17682
    assert record.token_totals.cached == 5978
    assert record.metadata["default_model"] == "gemini-3.1-pro-preview"


def test_copilot_detect_marks_plugin_only_state_as_unsupported(sample_home: Path) -> None:
    plugin_dir = sample_home / ".config" / "github-copilot"
    plugin_dir.mkdir(parents=True)
    write_json(plugin_dir / "apps.json", {"app": "plugin"})

    status = CopilotAdapter(home=sample_home).detect()
    assert status.status.value == "unsupported"
    assert status.ignored_paths
