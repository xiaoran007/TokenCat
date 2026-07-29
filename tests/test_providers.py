from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tokencat.core.models import ProviderName, ScanFilters
from tokencat.providers.antigravity import AntigravityAdapter
from tokencat.providers.claude import ClaudeAdapter
from tokencat.providers.codex import CodexAdapter
from tokencat.providers.copilot import CopilotAdapter
from tokencat.providers.gemini import GeminiAdapter

from conftest import create_codex_state_db, write_claude_session_jsonl, write_copilot_cli_session_state, write_json, write_jsonl


def _encode_varint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _protobuf_varint(field_number: int, value: int) -> bytes:
    return _encode_varint(field_number << 3) + _encode_varint(value)


def _protobuf_bytes(field_number: int, value: bytes) -> bytes:
    return _encode_varint((field_number << 3) | 2) + _encode_varint(len(value)) + value


def _antigravity_generation(
    *,
    timestamp: int,
    model: str,
    non_cached_input: int,
    cached_input: int,
    output: int,
) -> bytes:
    usage = b"".join(
        (
            _protobuf_varint(1, 1071),
            _protobuf_varint(2, non_cached_input),
            _protobuf_varint(3, output),
            _protobuf_varint(5, cached_input) if cached_input else b"",
            _protobuf_varint(6, 24),
        )
    )
    timestamp_payload = _protobuf_varint(1, timestamp) + _protobuf_varint(2, 0)
    timing = _protobuf_bytes(4, timestamp_payload)
    envelope = b"".join(
        (
            _protobuf_bytes(4, usage),
            _protobuf_bytes(9, timing),
            _protobuf_bytes(19, model.encode("utf-8")),
        )
    )
    return _protobuf_bytes(1, envelope)


def _write_antigravity_database(home: Path, root_name: str, session_id: str, generations: list[bytes]) -> Path:
    path = home / ".gemini" / root_name / "conversations" / f"{session_id}.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB, size INTEGER NOT NULL DEFAULT 0)")
        connection.executemany(
            "INSERT INTO gen_metadata (idx, data, size) VALUES (?, ?, ?)",
            [(index, generation, len(generation)) for index, generation in enumerate(generations)],
        )
    connection.close()
    return path


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


def test_antigravity_adapter_scans_app_and_cli_databases(sample_home: Path) -> None:
    app_path = _write_antigravity_database(
        sample_home,
        "antigravity",
        "app-session",
        [
            _antigravity_generation(
                timestamp=1773590861,
                model="gemini-3.6-flash",
                non_cached_input=100,
                cached_input=0,
                output=30,
            ),
            _antigravity_generation(
                timestamp=1773590871,
                model="gemini-3.6-flash",
                non_cached_input=200,
                cached_input=50,
                output=40,
            ),
        ],
    )
    cli_path = _write_antigravity_database(
        sample_home,
        "antigravity-cli",
        "cli-session",
        [
            _antigravity_generation(
                timestamp=1773590881,
                model="gemini-3.6-flash",
                non_cached_input=300,
                cached_input=75,
                output=50,
            )
        ],
    )

    adapter = AntigravityAdapter(home=sample_home)
    status = adapter.detect()
    sessions = {record.provider_session_id: record for record in adapter.scan(ScanFilters())}

    assert status.provider is ProviderName.ANTIGRAVITY
    assert status.status.value == "supported"
    assert status.found_paths == [sample_home / ".gemini" / "antigravity", sample_home / ".gemini" / "antigravity-cli"]
    assert set(sessions) == {"app-session", "cli-session"}

    app = sessions["app-session"]
    assert app.provider is ProviderName.ANTIGRAVITY
    assert app.source_refs == [app_path]
    assert app.primary_model == "gemini-3.6-flash"
    assert app.token_totals.input == 2540
    assert app.token_totals.output == 70
    assert app.token_totals.cached == 50
    assert app.token_totals.total == 2610
    assert app.model_usage["gemini-3.6-flash"].message_count == 2
    assert len(app.usage_slices) == 2
    assert app.started_at is not None
    assert app.updated_at is not None
    assert app.started_at < app.updated_at

    cli = sessions["cli-session"]
    assert cli.source_refs == [cli_path]
    assert cli.token_totals.input == 1470
    assert cli.token_totals.output == 50
    assert cli.token_totals.cached == 75
    assert cli.token_totals.total == 1520


def test_antigravity_adapter_deduplicates_conversation_ids_across_roots(sample_home: Path) -> None:
    generation = _antigravity_generation(
        timestamp=1773590861,
        model="gemini-3.6-flash",
        non_cached_input=100,
        cached_input=0,
        output=30,
    )
    app_path = _write_antigravity_database(sample_home, "antigravity", "shared-session", [generation])
    _write_antigravity_database(sample_home, "antigravity-cli", "shared-session", [generation])

    sessions = AntigravityAdapter(home=sample_home).scan(ScanFilters())

    assert len(sessions) == 1
    assert sessions[0].source_refs == [app_path]


def test_claude_detect_supports_modern_and_legacy_roots(sample_home: Path) -> None:
    write_claude_session_jsonl(
        sample_home,
        "legacy-project",
        "legacy-session",
        [
            {
                "type": "assistant",
                "timestamp": "2026-03-25T20:43:52.043Z",
                "sessionId": "legacy-session",
                "cwd": "/repo/legacy",
                "message": {
                    "id": "msg-legacy",
                    "role": "assistant",
                    "model": "claude-sonnet-4.6",
                    "usage": {
                        "input_tokens": 100,
                        "cache_creation_input_tokens": 20,
                        "cache_read_input_tokens": 10,
                        "output_tokens": 30,
                    },
                },
            }
        ],
    )
    write_claude_session_jsonl(
        sample_home,
        "modern-project",
        "modern-session",
        [
            {
                "type": "assistant",
                "timestamp": "2026-03-25T20:48:02.684Z",
                "sessionId": "modern-session",
                "cwd": "/repo/modern",
                "message": {
                    "id": "msg-modern",
                    "role": "assistant",
                    "model": "gpt-5",
                    "usage": {
                        "input_tokens": 50,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "output_tokens": 5,
                    },
                },
            }
        ],
        config_root=".config/claude",
    )

    status = ClaudeAdapter(home=sample_home, env={}).detect()

    assert status.status.value == "supported"
    assert any(str(path).endswith(".claude") for path in status.found_paths)
    assert any(str(path).endswith(".config/claude") for path in status.found_paths)


def test_claude_detect_uses_claude_config_dir_and_ignores_invalid_entries(sample_home: Path) -> None:
    custom_root = sample_home / "claude-custom"
    write_claude_session_jsonl(
        sample_home,
        "custom-project",
        "custom-session",
        [
            {
                "type": "assistant",
                "timestamp": "2026-03-25T20:43:52.043Z",
                "sessionId": "custom-session",
                "message": {
                    "id": "msg-custom",
                    "role": "assistant",
                    "model": "claude-sonnet-4.6",
                    "usage": {
                        "input_tokens": 40,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "output_tokens": 10,
                    },
                },
            }
        ],
        config_root="claude-custom",
    )
    env = {"CLAUDE_CONFIG_DIR": f"{custom_root},{sample_home / 'missing-claude-root'}"}

    status = ClaudeAdapter(home=sample_home, env=env).detect()
    sessions = ClaudeAdapter(home=sample_home, env=env).scan(ScanFilters())

    assert status.status.value == "supported"
    assert len(sessions) == 1
    assert sessions[0].provider_session_id == "custom-session"
    assert any("CLAUDE_CONFIG_DIR" in warning for warning in status.warnings)


def test_claude_adapter_scans_main_session_dedupes_updates_and_ignores_synthetic_rows(sample_home: Path) -> None:
    write_claude_session_jsonl(
        sample_home,
        "playground",
        "b7b58aba-3b85-475c-aa08-a28ea12020b4",
        [
            {
                "type": "user",
                "timestamp": "2026-03-25T20:38:42.001Z",
                "sessionId": "b7b58aba-3b85-475c-aa08-a28ea12020b4",
                "cwd": "/Users/xiaoran/Desktop/code/playground",
                "version": "2.1.83",
                "gitBranch": "HEAD",
                "entrypoint": "cli",
                "slug": "jolly-gathering-bentley",
            },
            {
                "type": "assistant",
                "timestamp": "2026-03-25T20:43:52.043Z",
                "sessionId": "b7b58aba-3b85-475c-aa08-a28ea12020b4",
                "message": {
                    "id": "msg_f68b6d6b53114616bd9f896e",
                    "role": "assistant",
                    "model": "Qwen3.5-27B-Claude-4.6-Opus-Distilled-MLX-6bit",
                    "usage": {"input_tokens": 23064, "output_tokens": 0},
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-03-25T20:44:22.651Z",
                "sessionId": "b7b58aba-3b85-475c-aa08-a28ea12020b4",
                "message": {
                    "id": "msg_f68b6d6b53114616bd9f896e",
                    "role": "assistant",
                    "model": "Qwen3.5-27B-Claude-4.6-Opus-Distilled-MLX-6bit",
                    "usage": {
                        "input_tokens": 23064,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "output_tokens": 369,
                    },
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-03-25T20:45:22.651Z",
                "sessionId": "b7b58aba-3b85-475c-aa08-a28ea12020b4",
                "isApiErrorMessage": True,
                "message": {
                    "id": "msg-api-error",
                    "role": "assistant",
                    "model": "claude-sonnet-4.6",
                    "usage": {"input_tokens": 500, "output_tokens": 500},
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-03-25T20:48:02.684Z",
                "sessionId": "b7b58aba-3b85-475c-aa08-a28ea12020b4",
                "message": {
                    "id": "msg-synthetic",
                    "role": "assistant",
                    "model": "<synthetic>",
                    "usage": {"input_tokens": 999, "output_tokens": 999},
                },
            },
        ],
    )

    sessions = ClaudeAdapter(home=sample_home, env={}).scan(ScanFilters())

    assert len(sessions) == 1
    record = sessions[0]
    assert record.provider_session_id == "b7b58aba-3b85-475c-aa08-a28ea12020b4"
    assert record.title == "jolly-gathering-bentley"
    assert record.cwd == "/Users/xiaoran/Desktop/code/playground"
    assert record.token_totals.input == 23064
    assert record.token_totals.output == 369
    assert record.token_totals.total == 23433
    assert record.primary_model == "Qwen3.5-27B-Claude-4.6-Opus-Distilled-MLX-6bit"
    assert record.model_usage["Qwen3.5-27B-Claude-4.6-Opus-Distilled-MLX-6bit"].message_count == 1
    assert record.metadata["session_kind"] == "main"
    assert record.metadata["git_branch"] == "HEAD"
    assert record.metadata["entrypoint"] == "cli"
    assert record.metadata["version"] == "2.1.83"
    assert record.attribution_status == "exact"


def test_claude_adapter_scans_subagent_as_separate_session(sample_home: Path) -> None:
    write_claude_session_jsonl(
        sample_home,
        "lab",
        "0463030f-09fb-4e36-815c-da9cacd01a1e",
        [
            {
                "type": "assistant",
                "timestamp": "2026-02-09T16:30:00.000Z",
                "sessionId": "0463030f-09fb-4e36-815c-da9cacd01a1e",
                "cwd": "/Users/xiaoran/Desktop/code/ENGN2500Lab",
                "message": {
                    "id": "msg-main",
                    "role": "assistant",
                    "model": "claude-sonnet-4-5-20250929",
                    "usage": {
                        "input_tokens": 500,
                        "cache_creation_input_tokens": 100,
                        "cache_read_input_tokens": 200,
                        "output_tokens": 50,
                    },
                },
            }
        ],
    )
    write_claude_session_jsonl(
        sample_home,
        "lab",
        "agent-a669e77",
        [
            {
                "type": "assistant",
                "timestamp": "2026-02-09T16:33:10.929Z",
                "sessionId": "0463030f-09fb-4e36-815c-da9cacd01a1e",
                "agentId": "a669e77",
                "isSidechain": True,
                "cwd": "/Users/xiaoran/Desktop/code/ENGN2500Lab",
                "message": {
                    "id": "msg-subagent",
                    "role": "assistant",
                    "model": "claude-haiku-4-5-20251001",
                    "usage": {
                        "input_tokens": 10,
                        "cache_creation_input_tokens": 1401,
                        "cache_read_input_tokens": 9974,
                        "output_tokens": 185,
                    },
                },
            }
        ],
        subdir="0463030f-09fb-4e36-815c-da9cacd01a1e/subagents",
    )

    sessions = {
        record.provider_session_id: record
        for record in ClaudeAdapter(home=sample_home, env={}).scan(ScanFilters())
    }

    assert set(sessions) == {
        "0463030f-09fb-4e36-815c-da9cacd01a1e",
        "0463030f-09fb-4e36-815c-da9cacd01a1e#agent:a669e77",
    }
    subagent = sessions["0463030f-09fb-4e36-815c-da9cacd01a1e#agent:a669e77"]
    assert subagent.metadata["session_kind"] == "subagent"
    assert subagent.metadata["parent_session_id"] == "0463030f-09fb-4e36-815c-da9cacd01a1e"
    assert subagent.metadata["agent_id"] == "a669e77"
    assert subagent.metadata["is_sidechain"] == "true"
    assert subagent.token_totals.input == 11385
    assert subagent.token_totals.cached == 9974
    assert subagent.token_totals.output == 185
    assert subagent.token_totals.total == 11570


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
