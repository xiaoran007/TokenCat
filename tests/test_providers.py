from __future__ import annotations

import json
from pathlib import Path

from tokencat.core.models import ScanFilters
from tokencat.providers.codex import CodexAdapter
from tokencat.providers.copilot import CopilotAdapter
from tokencat.providers.gemini import GeminiAdapter

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


def write_copilot_session_jsonl(
    home: Path,
    workspace_id: str,
    session_id: str,
    rows: list[dict[str, object]],
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
        / f"{session_id}.jsonl"
    )
    write_jsonl(path, rows)
    return path


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


def test_copilot_detect_marks_vscode_chat_sessions_as_supported(sample_home: Path) -> None:
    write_copilot_session_json(
        sample_home,
        "workspace-a",
        "session-a",
        {
            "sessionId": "session-a",
            "creationDate": 1771433087111,
            "customTitle": "Token support",
            "requests": [
                {
                    "timestamp": 1771433108061,
                    "modelId": "copilot/gpt-5.3-codex",
                    "result": {"usage": {"promptTokens": 24438, "completionTokens": 238}},
                }
            ],
        },
    )

    status = CopilotAdapter(home=sample_home).detect()

    assert status.status.value == "supported"
    assert any("workspaceStorage" in str(path) for path in status.found_paths)


def test_copilot_detect_marks_cli_session_state_as_supported(sample_home: Path) -> None:
    write_copilot_cli_session_state(
        sample_home,
        "cli-session-a",
        [
            {
                "timestamp": "2026-03-16T21:58:06.501Z",
                "type": "session.start",
                "data": {
                    "sessionId": "cli-session-a",
                    "startTime": "2026-03-16T21:58:06.501Z",
                },
            },
            {
                "timestamp": "2026-03-16T22:08:06.501Z",
                "type": "session.shutdown",
                "data": {
                    "sessionStartTime": "2026-03-16T21:58:06.501Z",
                    "currentModel": "claude-sonnet-4.6",
                    "shutdownType": "user_exit",
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
    )

    status = CopilotAdapter(home=sample_home).detect()

    assert status.status.value == "supported"
    assert any(".copilot/session-state" in str(path) for path in status.found_paths)


def test_copilot_detect_marks_active_cli_session_state_as_partial(sample_home: Path) -> None:
    write_copilot_cli_session_state(
        sample_home,
        "cli-session-active",
        [
            {
                "timestamp": "2026-03-16T21:58:06.501Z",
                "type": "session.start",
                "data": {
                    "sessionId": "cli-session-active",
                    "startTime": "2026-03-16T21:58:06.501Z",
                },
            },
            {
                "timestamp": "2026-03-16T22:00:06.501Z",
                "type": "assistant.message",
                "data": {"content": "do not leak this prompt body"},
            },
        ],
    )

    status = CopilotAdapter(home=sample_home).detect()
    sessions = CopilotAdapter(home=sample_home).scan(ScanFilters())

    assert status.status.value == "partial"
    assert sessions == []
    assert any("active sessions" in reason for reason in status.reasons)


def test_copilot_adapter_scans_jsonl_request_usage(sample_home: Path) -> None:
    write_copilot_session_jsonl(
        sample_home,
        "workspace-a",
        "session-a",
        [
            {
                "kind": 0,
                "v": {
                    "version": 3,
                    "creationDate": 1771433087111,
                    "customTitle": "Pairing",
                    "sessionId": "session-a",
                    "requests": [],
                },
            },
            {
                "kind": 2,
                "k": ["requests"],
                "v": [
                    {
                        "timestamp": 1771433108061,
                        "modelId": "copilot/gpt-5.3-codex",
                    }
                ],
            },
            {
                "kind": 1,
                "k": ["requests", 0, "result"],
                "v": {"usage": {"promptTokens": 24438, "completionTokens": 238}},
            },
        ],
    )

    sessions = CopilotAdapter(home=sample_home).scan(ScanFilters())

    assert len(sessions) == 1
    record = sessions[0]
    assert record.title == "Pairing"
    assert record.primary_model == "copilot/gpt-5.3-codex"
    assert record.token_totals.input == 24438
    assert record.token_totals.output == 238
    assert record.token_totals.total == 24676
    assert record.model_usage["copilot/gpt-5.3-codex"].message_count == 1
    assert record.metadata["request_count"] == 1
    assert record.attribution_status == "exact"


def test_copilot_adapter_scans_json_without_usage(sample_home: Path) -> None:
    write_copilot_session_json(
        sample_home,
        "workspace-b",
        "session-b",
        {
            "sessionId": "session-b",
            "creationDate": 1761790671719,
            "customTitle": "Metadata only",
            "requests": [
                {
                    "timestamp": 1761790672719,
                    "modelId": "copilot/gemini-2.5-pro",
                }
            ],
        },
    )

    adapter = CopilotAdapter(home=sample_home)
    status = adapter.detect()
    sessions = adapter.scan(ScanFilters())

    assert status.status.value == "partial"
    assert len(sessions) == 1
    assert sessions[0].title == "Metadata only"
    assert sessions[0].primary_model == "copilot/gemini-2.5-pro"
    assert sessions[0].token_totals.total == 0
    assert sessions[0].model_usage["copilot/gemini-2.5-pro"].message_count == 1


def test_copilot_adapter_aggregates_mixed_model_usage(sample_home: Path) -> None:
    write_copilot_session_json(
        sample_home,
        "workspace-c",
        "session-c",
        {
            "sessionId": "session-c",
            "creationDate": 1771964962718,
            "requests": [
                {
                    "timestamp": 1771964963718,
                    "modelId": "copilot/gpt-5.3-codex",
                    "result": {"usage": {"promptTokens": 1000, "completionTokens": 100}},
                },
                {
                    "timestamp": 1771964964718,
                    "modelId": "copilot/gemini-2.5-pro",
                    "result": {"usage": {"promptTokens": 500, "completionTokens": 50}},
                },
            ],
        },
    )

    sessions = CopilotAdapter(home=sample_home).scan(ScanFilters())

    assert len(sessions) == 1
    record = sessions[0]
    assert set(record.model_usage) == {"copilot/gpt-5.3-codex", "copilot/gemini-2.5-pro"}
    assert record.token_totals.total == 1650
    assert record.model_usage["copilot/gpt-5.3-codex"].tokens.total == 1100
    assert record.model_usage["copilot/gemini-2.5-pro"].tokens.total == 550


def test_copilot_adapter_ignores_empty_scaffold_sessions(sample_home: Path) -> None:
    write_copilot_session_jsonl(
        sample_home,
        "workspace-d",
        "session-d",
        [
            {
                "kind": 0,
                "v": {
                    "version": 3,
                    "creationDate": 1771433087111,
                    "sessionId": "session-d",
                    "requests": [],
                },
            }
        ],
    )

    adapter = CopilotAdapter(home=sample_home)
    status = adapter.detect()
    sessions = adapter.scan(ScanFilters())

    assert status.status.value == "partial"
    assert sessions == []


def test_copilot_adapter_scans_cli_session_state_shutdown_usage(sample_home: Path) -> None:
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
                "timestamp": "2026-03-16T22:01:10.000Z",
                "type": "assistant.message",
                "data": {"content": "never include this raw body in TokenCat"},
            },
            {
                "timestamp": "2026-03-16T22:08:06.501Z",
                "type": "session.shutdown",
                "data": {
                    "sessionStartTime": "2026-03-16T21:58:06.501Z",
                    "currentModel": "claude-sonnet-4.6",
                    "shutdownType": "user_exit",
                    "totalPremiumRequests": 1,
                    "totalApiDurationMs": 3210,
                    "modelMetrics": {
                        "claude-sonnet-4.6": {
                            "usage": {
                                "inputTokens": 428306,
                                "outputTokens": 8235,
                                "cacheReadTokens": 406292,
                                "cacheWriteTokens": 19,
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

    sessions = CopilotAdapter(home=sample_home).scan(ScanFilters())

    assert len(sessions) == 1
    record = sessions[0]
    assert record.provider_session_id == "cf76050a-de21-4ea4-84d4-15393a6791d9"
    assert record.primary_model == "claude-sonnet-4.6"
    assert record.cwd == "/repo/copilot-playground"
    assert record.token_totals.input == 428306
    assert record.token_totals.output == 8235
    assert record.token_totals.cached == 406292
    assert record.token_totals.total == 436541
    assert record.model_usage["claude-sonnet-4.6"].message_count == 16
    assert record.metadata["source"] == "copilot_cli_session_state"
    assert record.metadata["premium_requests"] == 1
    assert record.metadata["cache_write_tokens"] == 19
    assert record.metadata["request_count"] == 16
    assert record.metadata["request_cost"] == 1.0
    assert record.metadata["shutdown_type"] == "user_exit"
    assert record.attribution_status == "exact"
    assert "never include this raw body" not in json.dumps(record.metadata, ensure_ascii=False)


def test_copilot_adapter_scans_cli_session_state_multi_model_usage(sample_home: Path) -> None:
    write_copilot_cli_session_state(
        sample_home,
        "cli-session-multi",
        [
            {
                "timestamp": "2026-03-16T21:58:06.501Z",
                "type": "session.start",
                "data": {
                    "sessionId": "cli-session-multi",
                    "startTime": "2026-03-16T21:58:06.501Z",
                },
            },
            {
                "timestamp": "2026-03-16T22:08:06.501Z",
                "type": "session.shutdown",
                "data": {
                    "sessionStartTime": "2026-03-16T21:58:06.501Z",
                    "currentModel": "gemini-2.5-pro",
                    "modelMetrics": {
                        "claude-sonnet-4.6": {
                            "usage": {
                                "inputTokens": 100,
                                "outputTokens": 20,
                                "cacheReadTokens": 80,
                                "cacheWriteTokens": 3,
                            },
                            "requests": {"count": 2, "cost": 1},
                        },
                        "gemini-2.5-pro": {
                            "usage": {
                                "inputTokens": 50,
                                "outputTokens": 10,
                                "cacheReadTokens": 5,
                                "cacheWriteTokens": 7,
                            },
                            "requests": {"count": 1, "cost": 0},
                        },
                    },
                },
            },
        ],
    )

    sessions = CopilotAdapter(home=sample_home).scan(ScanFilters())

    assert len(sessions) == 1
    record = sessions[0]
    assert record.primary_model == "gemini-2.5-pro"
    assert set(record.model_usage) == {"claude-sonnet-4.6", "gemini-2.5-pro"}
    assert record.token_totals.input == 150
    assert record.token_totals.output == 30
    assert record.token_totals.cached == 85
    assert record.token_totals.total == 180
    assert record.metadata["request_count"] == 3
    assert record.metadata["cache_write_tokens"] == 10
    assert record.metadata["request_cost"] == 1.0


def test_copilot_adapter_cli_session_state_falls_back_to_directory_name(sample_home: Path) -> None:
    write_copilot_cli_session_state(
        sample_home,
        "fallback-dir-id",
        [
            {
                "timestamp": "2026-03-16T22:08:06.501Z",
                "type": "session.shutdown",
                "data": {
                    "sessionStartTime": "2026-03-16T21:58:06.501Z",
                    "currentModel": "claude-sonnet-4.6",
                    "modelMetrics": {
                        "claude-sonnet-4.6": {
                            "usage": {
                                "inputTokens": 10,
                                "outputTokens": 2,
                                "cacheReadTokens": 8,
                                "cacheWriteTokens": 0,
                            },
                            "requests": {"count": 1, "cost": 0},
                        }
                    },
                },
            },
        ],
    )

    sessions = CopilotAdapter(home=sample_home).scan(ScanFilters())

    assert len(sessions) == 1
    assert sessions[0].provider_session_id == "fallback-dir-id"


def test_copilot_detect_keeps_jetbrains_state_unscannable(sample_home: Path) -> None:
    plugin_dir = sample_home / ".config" / "github-copilot"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "copilot-intellij.db").write_text("", encoding="utf-8")

    status = CopilotAdapter(home=sample_home).detect()

    assert status.status.value == "unsupported"
