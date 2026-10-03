import importlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from tokencat_native.engine import Engine, public_dashboard
from tokencat_native.options import configuration
from conftest import PRIVATE_BODY, PRIVATE_ID, claude_row, write_rows


def config(home):
    return configuration(home=home, data_dir=None, pricing_path=None, codex_root=None,
                         claude_roots=[], opencode_root=None, antigravity_roots=[])


def query(providers=None):
    return {"since_ms": 1_790_899_200_000, "until_ms": 1_790_985_600_000,
            "timezone": "UTC", "providers": providers, "granularity": "day", "include_details": True}


def test_real_extension_collects_all_four_harnesses_without_exporting_private_data(all_sources):
    with Engine(config(all_sources)) as engine:
        engine.scan()
        snapshot = engine.query(query())
    assert {row["id"] for row in snapshot["providers"]} == {"codex", "claude", "opencode", "antigravity"}
    assert snapshot["summary"]["event_count"] == 4
    # This OpenCode fixture reports reasoning separately; Rust includes it once in output.
    assert snapshot["summary"]["output_tokens"] == 220
    assert snapshot["summary"]["reasoning_tokens"] == 60
    assert snapshot["timeline"][0]["details"]["session_count"] == 4
    payload = public_dashboard(snapshot)
    encoded = json.dumps(payload)
    assert "states" not in payload
    for private in (PRIVATE_BODY, PRIVATE_ID, "/PRIVATE_PROJECT"):
        assert private not in encoded
    assert all(row["id"].startswith("session:") for row in payload["sessions"])
    assert snapshot["sessions"][0]["id"] != payload["sessions"][0]["id"]


def test_reopen_and_append_keep_native_ledger_totals_without_replay(source_home):
    for _ in range(2):
        with Engine(config(source_home)) as engine:
            engine.scan()
            assert engine.query(query())["summary"]["cost"]["total_tokens"] == 1050
    path = source_home / f".claude/projects/example/{PRIVATE_ID}.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(claude_row("second", output=100)) + "\n")
    with Engine(config(source_home)) as engine:
        engine.scan()
        snapshot = engine.query(query())
    assert snapshot["summary"]["event_count"] == 2
    assert snapshot["summary"]["cost"]["total_tokens"] == 2150
    assert snapshot["timeline"][0]["details"]["session_count"] == 1


def test_provider_filter_and_parallel_queries_use_native_results(all_sources):
    with Engine(config(all_sources)) as engine:
        engine.scan()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: engine.query(query(["claude"])), range(8)))
    assert all(result["summary"]["event_count"] == 1 for result in results)
    assert all(result["summary"]["cost"]["total_tokens"] == 1050 for result in results)


def test_context_manager_closes_engine_after_query_error(source_home):
    engine = Engine(config(source_home))
    with pytest.raises(RuntimeError, match="Unknown timezone"):
        with engine:
            engine.query({**query(), "timezone": "invalid-zone"})
    engine.close()
    with pytest.raises(RuntimeError, match="closed"):
        engine.scan()
    with pytest.raises(RuntimeError, match="closed"):
        engine.query(query())


def test_missing_extension_reports_error_without_python_collector_fallback(monkeypatch, source_home):
    original = importlib.import_module
    def missing(name):
        if name == "tokencat_native._native":
            raise ImportError("test missing extension")
        return original(name)
    monkeypatch.setattr(importlib, "import_module", missing)
    with pytest.raises(RuntimeError, match="Cannot load the native candidate extension"):
        Engine(config(source_home))
    assert not (source_home / ".tokencat-candidate").exists()


def test_parent_relationships_are_remapped_to_anonymous_labels(source_home):
    row = claude_row("child")
    row["agentId"] = "PRIVATE_AGENT_ID"
    row["isSidechain"] = True
    write_rows(source_home, f".claude/projects/example/{PRIVATE_ID}/subagents/PRIVATE_AGENT_ID.jsonl", [row])
    with Engine(config(source_home)) as engine:
        engine.scan()
        snapshot = public_dashboard(engine.query(query()))
    parent = next(row for row in snapshot["sessions"] if row["parent_id"] is None)
    child = next(row for row in snapshot["sessions"] if row["parent_id"] is not None)
    assert child["parent_id"] == parent["id"]
    assert PRIVATE_ID not in json.dumps(snapshot)
    assert "PRIVATE_AGENT_ID" not in json.dumps(snapshot)
