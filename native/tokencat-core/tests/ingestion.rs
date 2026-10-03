use serde_json::{json, Value};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};
use tokencat_core::{collector::collect, model::*, store::Store};
static NEXT: AtomicU64 = AtomicU64::new(0);
struct Fixture {
    home: PathBuf,
    config: CoreConfig,
}
impl Fixture {
    fn new() -> Self {
        let home = std::env::temp_dir().join(format!(
            "tokencat-ingest-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&home).unwrap();
        let config = CoreConfig {
            home: home.clone(),
            database_path: home.join("usage.sqlite"),
            claude_roots: vec![],
            opencode_root: None,
            antigravity_roots: vec![],
            codex_root: None,
            pricing_path: None,
        };
        Self { home, config }
    }
    fn write(&self, path: &str, rows: &[Value]) -> PathBuf {
        let path = self.home.join(path);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(
            &path,
            rows.iter().map(|v| format!("{v}\n")).collect::<String>(),
        )
        .unwrap();
        path
    }
    fn store(&self) -> Store {
        Store::open(&self.config.database_path).unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.home);
    }
}
fn meta(session: &str) -> Value {
    json!({"type":"session_meta","timestamp":"2026-10-02T10:00:00Z","payload":{"id":session,"cwd":"/developer/repo"}})
}
fn context() -> Value {
    json!({"type":"turn_context","timestamp":"2026-10-02T10:00:00Z","payload":{"model":"gpt-5.4"}})
}
fn raw(input: u64, output: u64) -> Value {
    json!({"input_tokens":input,"cached_input_tokens":input/2,"output_tokens":output,"reasoning_output_tokens":output/2,"total_tokens":input+output})
}

#[test]
fn codex_model_service_metadata_survives_restart_and_does_not_capture_config() {
    let f = Fixture::new();
    let mut metadata = meta("custom");
    metadata["payload"]["model_provider"] = json!("private-service");
    metadata["payload"]["api_key"] = json!("PRIVATE_CREDENTIAL");
    let path = f.write(
        ".codex/sessions/custom.jsonl",
        &[metadata, context(), count(100, 20, 100)],
    );
    {
        let mut store = f.store();
        collect(&mut store, &f.config).unwrap();
        let events = store.events().unwrap();
        assert_eq!(events[0].model_provider.as_deref(), Some("private-service"));
        assert!(!serde_json::to_string(&events)
            .unwrap()
            .contains("PRIVATE_CREDENTIAL"));
    }
    let mut out = OpenOptions::new().append(true).open(path).unwrap();
    writeln!(out, "{}", json!({"type":"token_usage_record","timestamp":"2026-10-02T10:02:00Z", "payload":{"thread_id":"custom","response_id":"modern-response","model":"private-model","usage":raw(120,30)}})).unwrap();
    let mut store = f.store();
    collect(&mut store, &f.config).unwrap();
    let events = store.events().unwrap();
    assert_eq!(events.len(), 2);
    assert!(events
        .iter()
        .all(|event| event.model_provider.as_deref() == Some("private-service")));
    f.write(
        ".codex/sessions/default.jsonl",
        &[meta("default"), context(), count(100, 20, 100)],
    );
    collect(&mut store, &f.config).unwrap();
    assert_eq!(
        store
            .events()
            .unwrap()
            .iter()
            .find(|event| event.session_id == "default")
            .unwrap()
            .model_provider
            .as_deref(),
        Some("openai")
    );
}

#[test]
fn old_codex_cursor_replays_service_identity_once_without_duplicate_usage() {
    let f = Fixture::new();
    let mut metadata = meta("custom");
    metadata["payload"]["model_provider"] = json!("private-service");
    f.write(
        ".codex/sessions/custom.jsonl",
        &[metadata, context(), count(100, 20, 100)],
    );
    {
        let mut store = f.store();
        collect(&mut store, &f.config).unwrap();
    }
    let connection = rusqlite::Connection::open(&f.config.database_path).unwrap();
    connection.execute("UPDATE cursors SET payload=json_set(payload,'$.parser_state.context',json_remove(json_extract(payload,'$.parser_state.context'),'$.model_provider')) WHERE identity LIKE 'codex:%'",[]).unwrap();
    connection.execute("UPDATE events SET payload=json_set(payload,'$.model_provider','openai') WHERE provider='codex'",[]).unwrap();
    drop(connection);
    let mut store = f.store();
    let report = collect(&mut store, &f.config).unwrap();
    assert_eq!(report.files_changed, 1);
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].model_provider.as_deref(), Some("private-service"));
    assert_eq!(collect(&mut store, &f.config).unwrap().files_changed, 0);
}
fn count(input: u64, output: u64, last: u64) -> Value {
    json!({"type":"event_msg","timestamp":"2026-10-02T10:01:00Z","payload":{"type":"token_count","info":{"total_token_usage":raw(input,output),"last_token_usage":raw(last,output),"model_context_window":200000},"rate_limits":{"primary":{"used_percent":11.5,"window_minutes":300,"resets_at":1791000000}}}})
}
fn claude(output: u64, time: &str) -> Value {
    json!({"type":"assistant","timestamp":time,"sessionId":"main","cwd":"/developer/repo","message":{"role":"assistant","id":"msg1","model":"claude-sonnet-4-6","content":[{"type":"text","text":"PRIVATE PROMPT BODY"}],"usage":{"input_tokens":100,"cache_read_input_tokens":500,"cache_creation_input_tokens":300,"cache_creation":{"ephemeral_5m_input_tokens":100,"ephemeral_1h_input_tokens":200},"output_tokens":output}}})
}
#[test]
fn restart_append_and_quota_snapshots_do_not_duplicate_usage() {
    let f = Fixture::new();
    let path = f.write(
        ".codex/sessions/day/one.jsonl",
        &[
            meta("one"),
            context(),
            count(100, 20, 100),
            count(100, 20, 100),
        ],
    );
    {
        let mut store = f.store();
        let report = collect(&mut store, &f.config).unwrap();
        assert_eq!(report.events_upserted, 1);
        assert_eq!(store.events().unwrap()[0].tokens.total, Some(120));
        assert_eq!(store.states().unwrap().len(), 2);
    }
    let mut store = f.store();
    assert_eq!(collect(&mut store, &f.config).unwrap().files_changed, 0);
    let mut out = OpenOptions::new().append(true).open(path).unwrap();
    writeln!(out, "{}", count(160, 40, 60)).unwrap();
    collect(&mut store, &f.config).unwrap();
    let events = store.events().unwrap();
    assert_eq!(events.len(), 2);
    assert_eq!(
        events.iter().map(|v| v.tokens.total.unwrap()).sum::<u64>(),
        200
    );
}
#[test]
fn incomplete_line_waits_and_revisions_keep_first_timestamp() {
    let f = Fixture::new();
    let path = f.write(
        ".claude/projects/repo/main.jsonl",
        &[claude(10, "2026-10-02T10:00:00Z")],
    );
    let mut store = f.store();
    collect(&mut store, &f.config).unwrap();
    let revised = claude(30, "2026-10-02T10:02:00Z").to_string();
    let split = revised.len() / 2;
    let mut out = OpenOptions::new().append(true).open(&path).unwrap();
    out.write_all(&revised.as_bytes()[..split]).unwrap();
    collect(&mut store, &f.config).unwrap();
    assert_eq!(store.events().unwrap()[0].tokens.output, Some(10));
    drop(store);
    let mut store = f.store();
    out.write_all(&revised.as_bytes()[split..]).unwrap();
    out.write_all(b"\n").unwrap();
    collect(&mut store, &f.config).unwrap();
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].tokens.output, Some(30));
    assert_eq!(events[0].timestamp_ms, 1790935200000);
    assert_eq!(events[0].tokens.cache_write_5m, Some(100));
    assert_eq!(events[0].tokens.cache_write_1h, Some(200));
    let serialized = serde_json::to_string(&events).unwrap();
    assert!(!serialized.contains("PRIVATE"));
}
#[test]
fn copied_roots_and_archive_moves_are_logically_deduplicated() {
    let f = Fixture::new();
    let path = f.write(
        ".claude/projects/repo/main.jsonl",
        &[claude(10, "2026-10-02T10:00:00Z")],
    );
    f.write(
        ".config/claude/projects/repo/main.jsonl",
        &[claude(10, "2026-10-02T10:00:00Z")],
    );
    let codex = f.write(
        ".codex/sessions/day/one.jsonl",
        &[meta("one"), context(), count(100, 20, 100)],
    );
    let mut store = f.store();
    collect(&mut store, &f.config).unwrap();
    assert_eq!(store.events().unwrap().len(), 2);
    fs::create_dir_all(f.home.join(".codex/archived_sessions")).unwrap();
    fs::rename(codex, f.home.join(".codex/archived_sessions/one.jsonl")).unwrap();
    fs::remove_file(path).unwrap();
    assert_eq!(collect(&mut store, &f.config).unwrap().events_upserted, 0);
    assert_eq!(store.events().unwrap().len(), 2);
}
#[test]
fn malformed_records_warn_without_exposing_body_and_scan_continues() {
    let f = Fixture::new();
    let path = f.write(
        ".claude/projects/repo/main.jsonl",
        &[claude(10, "2026-10-02T10:00:00Z")],
    );
    let mut out = OpenOptions::new().append(true).open(path).unwrap();
    writeln!(out, "{{PRIVATE_SECRET_BROKEN_JSON").unwrap();
    writeln!(out, "{}", claude(30, "2026-10-02T10:02:00Z")).unwrap();
    let mut store = f.store();
    let report = collect(&mut store, &f.config).unwrap();
    assert_eq!(report.warnings.len(), 1);
    assert!(!report.warnings[0].contains("PRIVATE"));
    assert_eq!(store.events().unwrap()[0].tokens.output, Some(30));
}
#[test]
fn truncation_and_replacement_replay_retains_the_observed_ledger() {
    let f = Fixture::new();
    let path = f.write(
        ".codex/sessions/one.jsonl",
        &[meta("one"), context(), count(100, 20, 100)],
    );
    let mut store = f.store();
    collect(&mut store, &f.config).unwrap();
    fs::write(&path, format!("{}\n", meta("one"))).unwrap();
    let report = collect(&mut store, &f.config).unwrap();
    assert_eq!(report.warnings.len(), 1);
    assert_eq!(store.events().unwrap().len(), 1);
    f.write(
        "replacement",
        &[meta("one"), context(), count(100, 20, 100)],
    );
    fs::rename(f.home.join("replacement"), &path).unwrap();
    collect(&mut store, &f.config).unwrap();
    assert_eq!(store.events().unwrap().len(), 1);
}
#[test]
fn same_inode_rewrite_with_same_length_is_detected() {
    let f = Fixture::new();
    let path = f.write(
        ".claude/projects/repo/main.jsonl",
        &[claude(10, "2026-10-02T10:00:00Z")],
    );
    let mut store = f.store();
    collect(&mut store, &f.config).unwrap();
    fs::write(path, format!("{}\n", claude(20, "2026-10-02T10:00:00Z"))).unwrap();
    let report = collect(&mut store, &f.config).unwrap();
    assert_eq!(report.warnings.len(), 1);
    assert_eq!(store.events().unwrap().len(), 1);
    assert_eq!(store.events().unwrap()[0].tokens.output, Some(20));
}
#[test]
fn modern_response_identity_is_authoritative_over_context_counts() {
    let f = Fixture::new();
    let record = json!({"type":"token_usage_record","timestamp":"2026-10-02T10:01:00Z","payload":{"thread_id":"one","session_id":"instance","turn_id":"turn","root_turn_id":"turn","response_id":"resp1","usage":raw(100,20),"turn_token_usage":raw(100,20),"thread_token_usage":raw(100,20)}});
    f.write(
        ".codex/sessions/one.jsonl",
        &[
            meta("one"),
            context(),
            record.clone(),
            count(100, 20, 100),
            record,
            count(100, 20, 100),
        ],
    );
    let mut store = f.store();
    collect(&mut store, &f.config).unwrap();
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].id, "response:resp1");
    assert_eq!(events[0].attribution, "configured");
}
#[test]
fn fork_inherited_legacy_history_is_not_billed_again() {
    let f = Fixture::new();
    let mut fork = meta("fork");
    fork["timestamp"] = json!("2026-10-02T11:00:00Z");
    fork["payload"]["forked_from_id"] = json!("parent");
    f.write(
        ".codex/sessions/fork.jsonl",
        &[fork, context(), count(100, 20, 100)],
    );
    let mut store = f.store();
    collect(&mut store, &f.config).unwrap();
    assert!(store.events().unwrap().is_empty());
}
#[test]
fn claude_subagent_is_linked_to_main() {
    let f = Fixture::new();
    let mut child = claude(10, "2026-10-02T10:00:00Z");
    child["agentId"] = json!("agent-1");
    child["isSidechain"] = json!(true);
    f.write(
        ".claude/projects/repo/main/subagents/agent-1.jsonl",
        &[child],
    );
    let mut store = f.store();
    collect(&mut store, &f.config).unwrap();
    let sessions = store.sessions().unwrap();
    assert_eq!(sessions[0].id, "main#agent:agent-1");
    assert_eq!(sessions[0].parent_id.as_deref(), Some("main"));
}

#[test]
fn malformed_numeric_metadata_is_visible_and_never_overflows() {
    let f = Fixture::new();
    let mut invalid = claude(10, "2026-10-02T10:00:00Z");
    invalid["message"]["usage"]["input_tokens"] = json!(u64::MAX);
    f.write(
        ".claude/projects/repo/main.jsonl",
        &[invalid, claude(10, "2026-10-02T10:00:00Z")],
    );
    let mut store = f.store();
    let report = collect(&mut store, &f.config).unwrap();
    assert_eq!(report.warnings.len(), 1);
    assert!(report.warnings[0].contains("overflow"));
    assert_eq!(store.events().unwrap().len(), 1);
}
#[test]
fn parser_state_and_database_never_retain_content_or_read_credentials() {
    let f = Fixture::new();
    let path = f.write(
        ".claude/projects/repo/main.jsonl",
        &[claude(10, "2026-10-02T10:00:00Z")],
    );
    f.write(
        ".codex/auth.json",
        &[json!({"access_token":"NEVER_READ_CREDENTIAL"})],
    );
    f.write(
        ".claude/credentials.json",
        &[json!({"secret":"NEVER_READ_CREDENTIAL"})],
    );
    let mut store = f.store();
    let report = collect(&mut store, &f.config).unwrap();
    assert_eq!(report.files_discovered, 1);
    use std::os::unix::fs::MetadataExt;
    let stat = fs::metadata(path).unwrap();
    let cursor = store
        .load_cursor(&format!("claude:{}:{}", stat.dev(), stat.ino()))
        .unwrap()
        .unwrap();
    let state = serde_json::to_string(&cursor.parser_state).unwrap();
    assert!(!state.contains("PRIVATE"));
    assert!(!state.contains("content"));
    let db = fs::read(&f.config.database_path).unwrap();
    let text = String::from_utf8_lossy(&db);
    assert!(!text.contains("PRIVATE PROMPT BODY"));
    assert!(!text.contains("NEVER_READ_CREDENTIAL"));
}
#[test]
fn codex_override_and_claude_explicit_roots_are_respected() {
    let mut f = Fixture::new();
    f.write(
        ".codex/sessions/ignored.jsonl",
        &[meta("ignored"), context(), count(100, 20, 100)],
    );
    f.write(
        "custom-codex/sessions/one.jsonl",
        &[meta("one"), context(), count(100, 20, 100)],
    );
    f.write(
        ".claude/projects/repo/main.jsonl",
        &[claude(10, "2026-10-02T10:00:00Z")],
    );
    f.config.codex_root = Some(f.home.join("custom-codex"));
    f.config.claude_roots = vec![f.home.join("absent-claude")];
    let mut store = f.store();
    collect(&mut store, &f.config).unwrap();
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].session_id, "one");
}

#[test]
fn cumulative_reset_does_not_rebill_carried_last_response() {
    let f = Fixture::new();
    let first = count(100, 20, 100);
    let mut reset = count(50, 10, 100);
    reset["timestamp"] = json!("2026-10-02T10:02:00Z");
    reset["payload"]["info"]["last_token_usage"] =
        first["payload"]["info"]["last_token_usage"].clone();
    f.write(
        ".codex/sessions/one.jsonl",
        &[meta("one"), context(), first, reset],
    );
    let mut store = f.store();
    let report = collect(&mut store, &f.config).unwrap();
    assert_eq!(store.events().unwrap().len(), 1);
    assert!(report.warnings.iter().any(|v| v.contains("baseline reset")));
}
#[test]
fn unknown_codex_cache_split_is_not_presented_as_uncached_zero() {
    let f = Fixture::new();
    let mut record = json!({"type":"token_usage_record","timestamp":"2026-10-02T10:01:00Z","payload":{"thread_id":"one","response_id":"resp1","model":"gpt-5.4","usage":{"input_tokens":100,"output_tokens":20,"total_tokens":120}}});
    record["payload"]["usage"]["reasoning_output_tokens"] = json!(0);
    f.write(".codex/sessions/one.jsonl", &[meta("one"), record]);
    let mut store = f.store();
    collect(&mut store, &f.config).unwrap();
    let events = store.events().unwrap();
    assert!(events[0].incomplete);
    assert_eq!(events[0].tokens.input_uncached, None);
    assert_eq!(events[0].attribution, "reported");
}

#[test]
fn partial_cumulative_output_or_cache_recovers_without_rebilling_after_restart() {
    use tokencat_core::pricing::PricingCatalog;
    for missing in [
        "output_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
    ] {
        let f = Fixture::new();
        let mut initial = count(100, 20, 100);
        initial["payload"]["info"]["total_token_usage"]["cache_write_input_tokens"] = json!(10);
        let mut partial = count(200, 40, 100);
        partial["timestamp"] = json!("2026-10-02T10:02:00Z");
        partial["payload"]["info"]["total_token_usage"]["cache_write_input_tokens"] = json!(20);
        // Explicit null means unknown; absent cache-write defaults to zero in
        // the Codex protocol, unlike the required input/cache-read/output fields.
        partial["payload"]["info"]["total_token_usage"][missing] = Value::Null;
        let path = f.write(
            ".codex/sessions/one.jsonl",
            &[meta("one"), context(), initial, partial],
        );
        {
            let mut store = f.store();
            collect(&mut store, &f.config).unwrap();
            let events = store.events().unwrap();
            assert_eq!(events.len(), 2);
            assert!(events[1].incomplete);
        }
        let mut store = f.store();
        let mut recovered = count(300, 60, 100);
        recovered["timestamp"] = json!("2026-10-02T10:03:00Z");
        recovered["payload"]["info"]["total_token_usage"]["cache_write_input_tokens"] = json!(30);
        let mut next = count(400, 80, 100);
        next["timestamp"] = json!("2026-10-02T10:04:00Z");
        next["payload"]["info"]["total_token_usage"]["cache_write_input_tokens"] = json!(40);
        let mut out = OpenOptions::new().append(true).open(path).unwrap();
        writeln!(out, "{recovered}").unwrap();
        writeln!(out, "{next}").unwrap();
        collect(&mut store, &f.config).unwrap();
        let events = store.events().unwrap();
        assert_eq!(events.len(), 4);
        assert_eq!(
            events.iter().map(|v| v.tokens.total.unwrap()).sum::<u64>(),
            480
        );
        match missing {
            "output_tokens" => {
                assert_eq!(events[1].tokens.output, None);
                assert_eq!(events[2].tokens.output, None);
                assert_eq!(events[3].tokens.output, Some(20));
            }
            "cached_input_tokens" => {
                assert_eq!(events[1].tokens.cache_read, None);
                assert_eq!(events[2].tokens.cache_read, None);
                assert_eq!(events[3].tokens.cache_read, Some(50));
                assert_eq!(events[2].tokens.input_uncached, None);
            }
            _ => {
                assert_eq!(events[1].tokens.cache_write, None);
                assert_eq!(events[2].tokens.cache_write, None);
                assert_eq!(events[3].tokens.cache_write, Some(10));
                assert_eq!(events[2].tokens.input_uncached, None);
            }
        }
        let catalog = PricingCatalog::load(None).unwrap();
        for event in &events[1..3] {
            let price = catalog.price(event);
            assert!(price.unpriced);
            assert!(price.uncertain);
            assert!(price.priced_tokens < price.total_tokens);
        }
    }
}

#[test]
fn partial_total_recovery_does_not_rebill_known_categories() {
    let f = Fixture::new();
    let mut partial = count(200, 40, 100);
    partial["timestamp"] = json!("2026-10-02T10:02:00Z");
    partial["payload"]["info"]["total_token_usage"]["total_tokens"] = Value::Null;
    let path = f.write(
        ".codex/sessions/one.jsonl",
        &[meta("one"), context(), count(100, 20, 100), partial],
    );
    {
        let mut store = f.store();
        collect(&mut store, &f.config).unwrap();
    }
    let mut recovered = count(300, 60, 100);
    recovered["timestamp"] = json!("2026-10-02T10:03:00Z");
    let mut out = OpenOptions::new().append(true).open(path).unwrap();
    writeln!(out, "{recovered}").unwrap();
    let mut store = f.store();
    collect(&mut store, &f.config).unwrap();
    let events = store.events().unwrap();
    assert_eq!(events.len(), 3);
    assert_eq!(
        events.iter().map(|v| v.tokens.total.unwrap()).sum::<u64>(),
        360
    );
    assert_eq!(events[2].tokens.output, Some(20));
}

#[test]
fn nested_claude_subagents_keep_their_immediate_parent() {
    let f = Fixture::new();
    f.write(
        ".claude/projects/repo/main.jsonl",
        &[claude(10, "2026-10-02T10:00:00Z")],
    );
    let mut parent = claude(20, "2026-10-02T10:01:00Z");
    parent["agentId"] = json!("alpha");
    parent["isSidechain"] = json!(true);
    f.write(
        ".claude/projects/repo/main/subagents/agent-alpha.jsonl",
        &[parent],
    );
    let mut child = claude(30, "2026-10-02T10:02:00Z");
    child["agentId"] = json!("beta");
    child["isSidechain"] = json!(true);
    let path = f.write(
        ".claude/projects/repo/main/subagents/agent-alpha/subagents/agent-beta.jsonl",
        &[child.clone()],
    );
    {
        let mut store = f.store();
        collect(&mut store, &f.config).unwrap();
        let sessions = store.sessions().unwrap();
        let nested = sessions.iter().find(|s| s.id == "main#agent:beta").unwrap();
        assert_eq!(nested.parent_id.as_deref(), Some("main#agent:alpha"));
    }
    child["message"]["usage"]["output_tokens"] = json!(40);
    child["timestamp"] = json!("2026-10-02T10:03:00Z");
    let mut out = OpenOptions::new().append(true).open(path).unwrap();
    writeln!(out, "{child}").unwrap();
    let mut store = f.store();
    collect(&mut store, &f.config).unwrap();
    let sessions = store.sessions().unwrap();
    assert_eq!(sessions.len(), 3);
    assert_eq!(
        sessions
            .iter()
            .find(|s| s.id == "main#agent:beta")
            .unwrap()
            .parent_id
            .as_deref(),
        Some("main#agent:alpha")
    );
    assert_eq!(store.events().unwrap().len(), 3);
}

#[test]
fn missing_cumulative_object_does_not_rebill_last_only_usage_when_it_recovers() {
    let f = Fixture::new();
    let mut last_only = count(150, 40, 50);
    last_only["timestamp"] = json!("2026-10-02T10:02:00Z");
    last_only["payload"]["info"]["total_token_usage"] = Value::Null;
    last_only["payload"]["info"]["last_token_usage"] = raw(50, 20);
    let path = f.write(
        ".codex/sessions/one.jsonl",
        &[meta("one"), context(), count(100, 20, 100), last_only],
    );
    {
        let mut store = f.store();
        collect(&mut store, &f.config).unwrap();
    }
    let mut recovered = count(200, 60, 50);
    recovered["timestamp"] = json!("2026-10-02T10:03:00Z");
    recovered["payload"]["info"]["last_token_usage"] = Value::Null;
    let mut next = count(250, 80, 50);
    next["timestamp"] = json!("2026-10-02T10:04:00Z");
    let mut out = OpenOptions::new().append(true).open(path).unwrap();
    writeln!(out, "{recovered}").unwrap();
    writeln!(out, "{next}").unwrap();
    let mut store = f.store();
    let report = collect(&mut store, &f.config).unwrap();
    let events = store.events().unwrap();
    assert_eq!(events.len(), 3);
    assert_eq!(
        events.iter().map(|e| e.tokens.total.unwrap()).sum::<u64>(),
        260
    );
    assert!(events[1].incomplete);
    assert!(report
        .warnings
        .iter()
        .any(|w| w.contains("baseline recovered")));
}

#[test]
fn carried_last_usage_without_cumulative_counters_is_not_billed_twice() {
    for restore_with_carried_last in [true, false] {
        let f = Fixture::new();
        let mut last_only = count(150, 40, 50);
        last_only["timestamp"] = json!("2026-10-02T10:02:00Z");
        last_only["payload"]["info"]["total_token_usage"] = Value::Null;
        last_only["payload"]["info"]["last_token_usage"] = raw(50, 20);
        let mut repeated = last_only.clone();
        repeated["timestamp"] = json!("2026-10-02T10:03:00Z");
        let path = f.write(
            ".codex/sessions/one.jsonl",
            &[
                meta("one"),
                context(),
                count(100, 20, 100),
                last_only,
                repeated,
            ],
        );
        {
            let mut store = f.store();
            let report = collect(&mut store, &f.config).unwrap();
            let events = store.events().unwrap();
            assert_eq!(events.len(), 2);
            assert!(events[1].incomplete);
            assert_eq!(
                events.iter().map(|e| e.tokens.total.unwrap()).sum::<u64>(),
                190
            );
            assert!(report
                .warnings
                .iter()
                .any(|w| w.contains("ambiguous response count")));
        }
        let mut out = OpenOptions::new().append(true).open(path).unwrap();
        if restore_with_carried_last {
            let mut restored = count(150, 40, 50);
            restored["timestamp"] = json!("2026-10-02T10:04:00Z");
            restored["payload"]["info"]["last_token_usage"] = raw(50, 20);
            writeln!(out, "{restored}").unwrap();
        }
        let mut new_response = count(180, 70, 30);
        new_response["timestamp"] = json!("2026-10-02T10:05:00Z");
        new_response["payload"]["info"]["last_token_usage"] = raw(30, 30);
        writeln!(out, "{new_response}").unwrap();
        let mut store = f.store();
        let report = collect(&mut store, &f.config).unwrap();
        let events = store.events().unwrap();
        assert_eq!(events.len(), 3);
        assert_eq!(
            events.iter().map(|e| e.tokens.total.unwrap()).sum::<u64>(),
            250
        );
        assert_eq!(events[2].tokens.output, Some(30));
        assert_eq!(events[2].tokens.cache_read, Some(15));
        if restore_with_carried_last {
            assert!(report
                .warnings
                .iter()
                .any(|w| w.contains("baseline recovered with unchanged last usage")));
        } else {
            assert!(events[2].incomplete);
        }
    }
}
