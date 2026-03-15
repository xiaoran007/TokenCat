from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from tokencat.cli import app
from tokencat.core.aggregate import aggregate_daily, aggregate_models, aggregate_summary
from tokencat.core.models import ModelUsage, PricingCatalog, PricingEntry, ProviderName, ScanFilters, SessionRecord, TokenTotals
from tokencat.core.pricing import apply_pricing, load_pricing_catalog, refresh_builtin_pricing
from tokencat.core.render import render_dashboard
from tokencat.core.time import parse_datetime_value
from tokencat.providers.registry import scan_providers

from conftest import create_codex_state_db, write_json, write_jsonl


def seed_dashboard_sample(home: Path, *, unknown_gemini: bool = False) -> None:
    codex_dir = home / ".codex"
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
                "payload": {"turn_id": "turn-1", "model": "gpt-5.3-codex"},
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
        [{"id": "019cf23f-a38c-7c21-b2f2-ecbb145c1652", "thread_name": "Build TokenCat"}],
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
            )
        ],
    )

    gemini_model = "gemini-3-pro-preview" if unknown_gemini else "gemini-2.5-pro"
    write_json(home / ".gemini" / "settings.json", {"model": {"name": "gemini-3.1-pro-preview"}})
    write_json(
        home / ".gemini" / "tmp" / "temp" / "chats" / "session-2026-03-14T00-04-19b8af10.json",
        {
            "sessionId": "19b8af10-5307-4b43-a9c3-97cecb7ebbfd",
            "startTime": "2026-03-14T00:07:11.272Z",
            "lastUpdated": "2026-03-14T00:07:39.001Z",
            "projectHash": "project-hash",
            "messages": [
                {
                    "timestamp": "2026-03-14T00:07:39.001Z",
                    "model": gemini_model,
                    "tokens": {"input": 1000, "output": 200, "cached": 100, "thoughts": 50, "tool": 0, "total": 1350},
                }
            ],
        },
    )


def build_dashboard_render_output(home: Path) -> str:
    result = scan_providers(ScanFilters(since=parse_datetime_value("7d", bound="since")))
    catalog = load_pricing_catalog(home)
    coverage = apply_pricing(result.sessions, catalog)
    summary = aggregate_summary(result.sessions, pricing_coverage=coverage)
    daily = aggregate_daily(result.sessions)
    models = aggregate_models(result.sessions)
    console = Console(width=100, force_terminal=False, color_system=None, record=True)
    render_dashboard(
        console,
        time_label="7d",
        statuses=result.statuses,
        summary=summary,
        daily=daily[-7:],
        top_models=models,
        sessions=result.sessions[:6],
        pricing_catalog=catalog,
        pricing_coverage=coverage,
        warnings=result.warnings,
    )
    return console.export_text()


def test_root_command_defaults_to_dashboard_json(sample_home: Path, monkeypatch) -> None:
    seed_dashboard_sample(sample_home)
    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)
    runner = CliRunner()

    result = runner.invoke(app, ["--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert set(payload["summary"]) == {"overview", "daily", "top_models", "recent_sessions", "pricing"}
    assert payload["summary"]["overview"]["pricing_coverage"]["priced_tokens"] > 0


def test_summary_keeps_envelope_and_adds_pricing_coverage(sample_home: Path, monkeypatch) -> None:
    seed_dashboard_sample(sample_home)
    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)
    runner = CliRunner()

    result = runner.invoke(app, ["summary", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert set(payload) == {"generated_at", "filters", "providers", "summary", "warnings"}
    assert "pricing_coverage" in payload["summary"]
    assert payload["summary"]["estimated_cost"]["total_cost"] > 0


def test_pricing_show_reports_unknown_models(sample_home: Path, monkeypatch) -> None:
    seed_dashboard_sample(sample_home, unknown_gemini=True)
    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)
    runner = CliRunner()

    result = runner.invoke(app, ["pricing", "show", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["summary"]["pricing"]["unknown_models"] == ["gemini-3-pro-preview"]
    assert payload["summary"]["pricing"]["coverage"]["priced_tokens"] == 180


def test_refresh_builtin_pricing_writes_cache(sample_home: Path) -> None:
    raw_dataset = {
        "gpt-5": {
            "input_cost_per_token": 1.25e-6,
            "output_cost_per_token": 1.0e-5,
            "cache_read_input_token_cost": 1.25e-7,
        },
        "gpt-5.2-codex": {
            "input_cost_per_token": 1.75e-6,
            "output_cost_per_token": 1.4e-5,
            "cache_read_input_token_cost": 1.75e-7,
        },
        "gemini/gemini-2.5-pro": {
            "input_cost_per_token": 1.25e-6,
            "output_cost_per_token": 1.0e-5,
            "cache_read_input_token_cost": 1.25e-7,
        },
    }
    catalog = refresh_builtin_pricing(sample_home, raw_dataset=raw_dataset)
    assert catalog.cache_path is not None
    assert catalog.cache_path.exists()
    loaded = load_pricing_catalog(sample_home)
    assert loaded.source == "cache"
    payload = json.loads(catalog.cache_path.read_text(encoding="utf-8"))
    models = {entry["model"] for entry in payload["entries"]}
    assert "gpt-5" in models
    assert "gemini-2.5-pro" in models


def test_dashboard_render_matches_golden_files(sample_home: Path, monkeypatch) -> None:
    seed_dashboard_sample(sample_home)
    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)
    rendered = build_dashboard_render_output(sample_home)
    expected = (Path(__file__).parent / "golden" / "dashboard_priced.txt").read_text(encoding="utf-8")
    assert rendered == expected


def test_dashboard_render_unknown_pricing_matches_golden(sample_home: Path, monkeypatch) -> None:
    seed_dashboard_sample(sample_home, unknown_gemini=True)
    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)
    rendered = build_dashboard_render_output(sample_home)
    expected = (Path(__file__).parent / "golden" / "dashboard_unknown.txt").read_text(encoding="utf-8")
    assert rendered == expected


def test_dashboard_render_without_pricing_matches_golden(sample_home: Path, monkeypatch) -> None:
    seed_dashboard_sample(sample_home)
    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)
    result = scan_providers(ScanFilters(since=parse_datetime_value("7d", bound="since")))
    summary = aggregate_summary(result.sessions, pricing_coverage=None)
    daily = aggregate_daily(result.sessions)
    models = aggregate_models(result.sessions)
    console = Console(width=100, force_terminal=False, color_system=None, record=True)
    render_dashboard(
        console,
        time_label="7d",
        statuses=result.statuses,
        summary=summary,
        daily=daily[-7:],
        top_models=models,
        sessions=result.sessions[:6],
        pricing_catalog=None,
        pricing_coverage=None,
        warnings=result.warnings,
    )
    rendered = console.export_text()
    expected = (Path(__file__).parent / "golden" / "dashboard_no_price.txt").read_text(encoding="utf-8")
    assert rendered == expected


def test_codex_dashboard_and_models_agree_for_recent_active_sessions(sample_home: Path, monkeypatch) -> None:
    seed_dashboard_sample(sample_home)
    monkeypatch.setattr("pathlib.Path.home", lambda: sample_home)
    runner = CliRunner()

    dashboard_result = runner.invoke(app, ["dashboard", "--provider", "codex", "--json"])
    models_result = runner.invoke(app, ["models", "--provider", "codex", "--json"])

    assert dashboard_result.exit_code == 0
    assert models_result.exit_code == 0

    dashboard_payload = json.loads(dashboard_result.stdout)
    models_payload = json.loads(models_result.stdout)

    assert dashboard_payload["summary"]["overview"]["token_totals"]["total"] == 180
    assert dashboard_payload["summary"]["daily"][0]["models"] == ["gpt-5.3-codex"]
    assert models_payload["items"][0]["model"] == "gpt-5.3-codex"
    assert models_payload["items"][0]["token_totals"]["total"] == 180


def test_apply_pricing_uses_aliases_and_leaves_unknown_models_unpriced() -> None:
    loaded_at = datetime.now().astimezone()
    catalog = PricingCatalog(
        source="builtin",
        loaded_at=loaded_at,
        entries={
            (ProviderName.CODEX, "gpt-5"): PricingEntry(
                provider=ProviderName.CODEX,
                model="gpt-5",
                input_per_1m=1.25,
                output_per_1m=10.0,
                cached_input_per_1m=0.125,
                currency="USD",
                effective_date="2026-03-15",
                source_url="https://example.test/pricing",
            ),
            (ProviderName.CODEX, "gpt-5.2-codex"): PricingEntry(
                provider=ProviderName.CODEX,
                model="gpt-5.2-codex",
                input_per_1m=1.75,
                output_per_1m=14.0,
                cached_input_per_1m=0.175,
                currency="USD",
                effective_date="2026-03-15",
                source_url="https://example.test/pricing",
            ),
        },
    )
    alias_record = SessionRecord(
        provider=ProviderName.CODEX,
        provider_session_id="alias-session",
        anon_session_id="alias-session",
        started_at=None,
        updated_at=None,
        token_totals=TokenTotals(input=1000, output=100, cached=200, total=1100),
        model_usage={
            "gpt-5-codex": ModelUsage(
                model="gpt-5-codex",
                tokens=TokenTotals(input=1000, output=100, cached=200, total=1100),
                attribution_status="exact",
            )
        },
    )
    newer_alias_record = SessionRecord(
        provider=ProviderName.CODEX,
        provider_session_id="alias-session-2",
        anon_session_id="alias-session-2",
        started_at=None,
        updated_at=None,
        token_totals=TokenTotals(input=1200, output=120, cached=240, total=1320),
        model_usage={
            "gpt-5.3-codex": ModelUsage(
                model="gpt-5.3-codex",
                tokens=TokenTotals(input=1200, output=120, cached=240, total=1320),
                attribution_status="exact",
            )
        },
    )
    unknown_record = SessionRecord(
        provider=ProviderName.CODEX,
        provider_session_id="unknown-session",
        anon_session_id="unknown-session",
        started_at=None,
        updated_at=None,
        token_totals=TokenTotals(input=500, output=50, cached=100, total=550),
        model_usage={
            "gpt-5.4": ModelUsage(
                model="gpt-5.4",
                tokens=TokenTotals(input=500, output=50, cached=100, total=550),
                attribution_status="exact",
            )
        },
    )

    coverage = apply_pricing([alias_record, newer_alias_record, unknown_record], catalog)

    assert coverage is not None
    assert alias_record.model_usage["gpt-5-codex"].pricing_status == "fallback_priced"
    assert alias_record.model_usage["gpt-5-codex"].pricing_model == "gpt-5"
    assert newer_alias_record.model_usage["gpt-5.3-codex"].pricing_status == "fallback_priced"
    assert newer_alias_record.model_usage["gpt-5.3-codex"].pricing_model == "gpt-5.2-codex"
    assert unknown_record.model_usage["gpt-5.4"].pricing_status == "unknown_model"
    assert coverage.unknown_models == ["gpt-5.4"]
    assert coverage.unknown_model_tokens == 550
