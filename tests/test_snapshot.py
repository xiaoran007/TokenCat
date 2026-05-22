from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from typer.testing import CliRunner

from tokencat.cli import app
from tokencat.core.models import DashboardUsageGranularity, ProviderName, ScanFilters
from tokencat.core.snapshot import build_snapshot

from conftest import create_codex_state_db, write_json, write_jsonl


def seed_snapshot_pricing_cache(home: Path) -> None:
    write_json(
        home / ".tokencat" / "pricing" / "bootstrap.json",
        {"attempted_at": "2026-03-16T00:00:00+00:00", "succeeded": False},
    )
    write_json(
        home / ".tokencat" / "pricing" / "catalog.json",
        {
            "source_url": "https://example.test/pricing",
            "refreshed_at": "2026-03-15T00:00:00+00:00",
            "entries": [
                {
                    "provider": "codex",
                    "model": "gpt-5",
                    "input_per_1m": 1.25,
                    "output_per_1m": 10.0,
                    "cached_input_per_1m": 0.125,
                    "currency": "USD",
                    "effective_date": "2026-03-15",
                    "source_url": "https://example.test/pricing",
                    "notes": [],
                }
            ],
        },
    )


def seed_snapshot_codex_session(home: Path) -> None:
    codex_dir = home / ".codex"
    write_jsonl(
        codex_dir / "sessions" / "2026" / "03" / "15" / "rollout-2026-03-15T16-07-41-snapshot-session.jsonl",
        [
            {
                "timestamp": "2026-03-15T16:07:41.000Z",
                "type": "session_meta",
                "payload": {
                    "id": "snapshot-session",
                    "timestamp": "2026-03-15T16:07:41.000Z",
                    "cwd": "/private/repo/project",
                    "source": "vscode",
                    "model_provider": "openai",
                    "cli_version": "0.115.0-alpha.4",
                },
            },
            {
                "timestamp": "2026-03-15T16:08:00.000Z",
                "type": "turn_context",
                "payload": {"turn_id": "turn-1", "model": "gpt-5"},
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
    write_jsonl(codex_dir / "session_index.jsonl", [{"id": "snapshot-session", "thread_name": "Secret Local Title"}])
    create_codex_state_db(
        codex_dir / "state_5.sqlite",
        [
            (
                "snapshot-session",
                1773590861,
                1773590961,
                "vscode",
                "openai",
                "/private/repo/project",
                "Secret Local Title",
                180,
                "0.115.0-alpha.4",
            )
        ],
    )


def test_build_snapshot_uses_stable_privacy_preserving_shape(sample_home: Path, monkeypatch) -> None:
    seed_snapshot_codex_session(sample_home)
    seed_snapshot_pricing_cache(sample_home)
    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)

    payload = build_snapshot(
        ScanFilters(
            providers={ProviderName.CODEX},
            since=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        ),
        pricing_enabled=True,
        usage_granularity=DashboardUsageGranularity.DAILY,
    )

    assert payload["schema_version"] == 1
    assert payload["filters"]["providers"] == ["codex"]
    assert payload["overview"]["session_count"] == 1
    assert payload["usage"]["granularity"] == "daily"
    assert payload["usage"]["records"][0]["token_totals"]["total"] == 180
    assert payload["top_models"][0]["model"] == "gpt-5"
    assert payload["pricing"]["catalog"]["model_count"] == 1
    assert payload["pricing"]["coverage"]["priced_tokens"] == 180

    encoded = json.dumps(payload, ensure_ascii=False)
    assert "Secret Local Title" not in encoded
    assert "/private/repo/project" not in encoded
    assert "found_paths" not in encoded
    assert "cache_path" not in encoded


def test_snapshot_cli_emits_json_without_pricing(sample_home: Path, monkeypatch) -> None:
    seed_snapshot_codex_session(sample_home)
    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)
    runner = CliRunner()

    result = runner.invoke(app, ["snapshot", "--provider", "codex", "--since", "2026-01-01", "--no-price"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["overview"]["token_totals"]["total"] == 180
    assert payload["pricing"]["catalog"] is None
    assert payload["pricing"]["coverage"] is None


def test_snapshot_cli_rejects_multiple_granularity_flags(sample_home: Path, monkeypatch) -> None:
    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)
    runner = CliRunner()

    result = runner.invoke(app, ["snapshot", "--daily", "--weekly"])

    assert result.exit_code == 2
    assert "Choose at most one" in result.stdout
