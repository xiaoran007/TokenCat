use rusqlite::{params, Connection};
use serde_json::{json, Value};
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};
use tokencat_core::{model::*, opencode::collect, store::Store};

static NEXT: AtomicU64 = AtomicU64::new(0);
struct Fixture {
    home: PathBuf,
    config: CoreConfig,
    source: Connection,
}

impl Fixture {
    fn new() -> Self {
        let home = std::env::temp_dir().join(format!(
            "tokencat-opencode-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let root = home.join(".local/share/opencode");
        fs::create_dir_all(&root).unwrap();
        let source = Connection::open(root.join("opencode.db")).unwrap();
        source.execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA wal_autocheckpoint=0;
             CREATE TABLE session(id TEXT PRIMARY KEY,parent_id TEXT,directory TEXT,time_created INTEGER);
             CREATE TABLE message(id TEXT PRIMARY KEY,session_id TEXT,time_created INTEGER,time_updated INTEGER,data TEXT);
             CREATE TABLE part(id TEXT PRIMARY KEY,message_id TEXT,session_id TEXT,time_created INTEGER,time_updated INTEGER,data TEXT);
             CREATE TABLE session_message(id TEXT PRIMARY KEY,session_id TEXT,type TEXT,time_created INTEGER,time_updated INTEGER,seq INTEGER,data TEXT);"
        ).unwrap();
        let config: CoreConfig = serde_json::from_value(json!({
            "home":home,"database_path":home.join("ledger.sqlite"),
            "codex_root":null,"claude_roots":[],"opencode_root":null,
            "antigravity_roots":[],"pricing_path":null
        }))
        .unwrap();
        Self {
            home,
            config,
            source,
        }
    }

    fn session(&self, id: &str, parent: Option<&str>, created: i64) {
        self.source
            .execute(
                "INSERT INTO session VALUES(?1,?2,'/developer/project',?3)",
                params![id, parent, created],
            )
            .unwrap();
    }

    fn message(&self, id: &str, session: &str, created: i64, usage: Value) {
        let data = json!({
            "role":"assistant","modelID":"deepseek-flash","providerID":"deepseek",
            "time":{"created":created,"completed":created+100}, "tokens":usage,
            "content":[{"text":"PRIVATE_RESPONSE_BODY"}],"error":{"message":"PRIVATE_ERROR_BODY"}
        });
        self.source
            .execute(
                "INSERT OR REPLACE INTO message VALUES(?1,?2,?3,?3,?4)",
                params![id, session, created, data.to_string()],
            )
            .unwrap();
    }

    fn step(&self, id: &str, message: &str, session: &str, created: i64, usage: Value) {
        let data =
            json!({"type":"step-finish","tokens":usage,"cost":999,"text":"PRIVATE_PART_BODY"});
        self.source
            .execute(
                "INSERT OR REPLACE INTO part VALUES(?1,?2,?3,?4,?4,?5)",
                params![id, message, session, created, data.to_string()],
            )
            .unwrap();
    }

    fn modern(&self, id: &str, session: &str, created: i64, usage: Value) {
        let data = json!({"model":{"id":"gpt-5.4","providerID":"openai"},"tokens":usage,"content":[{"text":"PRIVATE_MODERN_BODY"}]});
        self.source
            .execute(
                "INSERT INTO session_message VALUES(?1,?2,'assistant',?3,?3,1,?4)",
                params![id, session, created, data.to_string()],
            )
            .unwrap();
    }

    fn store(&self) -> Store {
        Store::open(&self.config.database_path).unwrap()
    }
    fn scan(&self, store: &mut Store) -> ScanReport {
        let mut report = ScanReport::default();
        collect(store, &self.config, &mut report).unwrap();
        report
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.home);
    }
}

fn usage(output: u64) -> Value {
    json!({"input":100,"output":output,"reasoning":20,"cache":{"read":500,"write":50}})
}

#[test]
fn reads_wal_usage_without_bodies_or_double_charging_reasoning() {
    let f = Fixture::new();
    f.session("main", None, 1000);
    f.message("msg1", "main", 1100, usage(30));
    f.step("part1", "msg1", "main", 1200, usage(30));
    let db = f.home.join(".local/share/opencode/opencode.db");
    let wal = f.home.join(".local/share/opencode/opencode.db-wal");
    let db_before = fs::read(&db).unwrap();
    let wal_before = fs::read(&wal).unwrap();
    let mut store = f.store();
    let report = f.scan(&mut store);
    assert_eq!(report.events_upserted, 1);
    let events = store.events().unwrap();
    let event = &events[0];
    assert_eq!(event.provider, Provider::OpenCode);
    assert_eq!(event.model.as_deref(), Some("deepseek-flash"));
    assert_eq!(event.model_provider.as_deref(), Some("deepseek"));
    assert_eq!(event.tokens.input_uncached, Some(100));
    assert_eq!(event.tokens.output, Some(50));
    assert_eq!(event.tokens.reasoning, Some(20));
    assert_eq!(event.tokens.total, Some(700));
    assert!(!event.incomplete);
    assert_eq!(event.tokens.cache_write_5m, None);
    assert_eq!(event.tokens.cache_write_1h, None);
    assert_eq!(fs::read(db).unwrap(), db_before);
    assert_eq!(fs::read(wal).unwrap(), wal_before);
    let payload = serde_json::to_string(&(events, store.sessions().unwrap())).unwrap();
    assert!(!payload.contains("PRIVATE"));
}

#[test]
fn changes_in_wal_revise_stable_events_and_survive_restart() {
    let f = Fixture::new();
    f.session("main", None, 1000);
    f.message("msg1", "main", 1100, usage(10));
    {
        let mut store = f.store();
        assert_eq!(f.scan(&mut store).events_upserted, 1);
        assert_eq!(f.scan(&mut store).files_changed, 0);
    }
    // The final step arrives later, without changing the original message ID.
    f.step("part1", "msg1", "main", 1200, usage(30));
    let mut store = f.store();
    assert_eq!(f.scan(&mut store).events_upserted, 1);
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].timestamp_ms, 1100);
    assert_eq!(events[0].tokens.output, Some(50));
    f.step("part1", "msg1", "main", 1200, usage(40));
    assert_eq!(f.scan(&mut store).files_changed, 1);
    assert_eq!(store.events().unwrap()[0].tokens.output, Some(60));
    assert_eq!(f.scan(&mut store).files_changed, 0);
}

#[test]
fn every_step_counts_once_even_when_message_only_keeps_last_step() {
    let f = Fixture::new();
    f.session("main", None, 1000);
    f.message("msg1", "main", 1100, usage(90));
    f.step("part1", "msg1", "main", 1200, usage(30));
    f.step("part2", "msg1", "main", 1300, usage(90));
    let mut store = f.store();
    f.scan(&mut store);
    let events = store.events().unwrap();
    assert_eq!(events.len(), 2);
    assert_eq!(
        events
            .iter()
            .map(|event| event.tokens.output.unwrap())
            .sum::<u64>(),
        160
    );
    assert_eq!(events[0].id, "message:msg1");
    assert_eq!(events[1].id, "step:part2");
}

#[test]
fn fork_context_is_not_new_usage_and_subagent_parent_is_preserved() {
    let f = Fixture::new();
    f.session("original", None, 1000);
    f.message("original-msg", "original", 1100, usage(30));
    f.session("fork", None, 2000);
    f.message("copied-msg", "fork", 1100, usage(30));
    f.step("copied-part", "copied-msg", "fork", 2100, usage(30));
    f.message("new-msg", "fork", 2200, usage(30));
    f.session("child", Some("original"), 1500);
    f.message("child-msg", "child", 1600, usage(30));
    let mut store = f.store();
    f.scan(&mut store);
    assert_eq!(store.events().unwrap().len(), 3);
    assert_eq!(
        store
            .sessions()
            .unwrap()
            .iter()
            .find(|session| session.id == "child")
            .unwrap()
            .parent_id
            .as_deref(),
        Some("original")
    );
}

#[test]
fn supports_new_projection_without_counting_a_mirror_twice() {
    let f = Fixture::new();
    f.session("main", None, 1000);
    f.message("same", "main", 1100, usage(30));
    f.modern("same", "main", 1100, usage(30));
    f.modern("new", "main", 1200, usage(60));
    let mut store = f.store();
    f.scan(&mut store);
    let events = store.events().unwrap();
    assert_eq!(events.len(), 2);
    assert_eq!(events[1].model.as_deref(), Some("gpt-5.4"));
    assert_eq!(events[1].model_provider.as_deref(), Some("openai"));
}

#[test]
fn missing_categories_stay_unknown_and_zero_or_absent_usage_is_ignored() {
    let f = Fixture::new();
    f.session("main", None, 1000);
    f.message(
        "partial",
        "main",
        1100,
        json!({"input":100,"output":20,"total":150}),
    );
    f.message(
        "empty",
        "main",
        1200,
        json!({"input":0,"output":0,"reasoning":0,"cache":{"read":0,"write":0}}),
    );
    f.message("absent", "main", 1300, Value::Null);
    let mut store = f.store();
    f.scan(&mut store);
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].tokens.cache_read, None);
    assert_eq!(events[0].tokens.cache_write, None);
    assert_eq!(events[0].tokens.reasoning, None);
    assert_eq!(events[0].tokens.output, None);
    assert_eq!(events[0].tokens.total, Some(150));
    assert!(events[0].incomplete);
}

#[test]
fn partial_usage_without_reported_total_retains_known_output_tokens() {
    let f = Fixture::new();
    f.session("main", None, 1000);
    f.message(
        "partial",
        "main",
        1100,
        json!({"input":100,"output":20,"cache":{"read":0,"write":0}}),
    );
    let mut store = f.store();
    f.scan(&mut store);
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].tokens.output, None);
    assert_eq!(events[0].tokens.reasoning, None);
    assert_eq!(events[0].tokens.total, Some(120));
    assert!(events[0].incomplete);
    f.message(
        "partial",
        "main",
        1100,
        json!({"input":100,"output":20,"cache":{"read":0,"write":0},"total":100}),
    );
    f.scan(&mut store);
    let revised = store.events().unwrap();
    assert_eq!(revised[0].tokens.total, Some(120));
    assert!(revised[0].incomplete);
}

#[test]
fn invalid_counts_do_not_expose_source_values_or_prevent_other_usage() {
    let f = Fixture::new();
    f.session("main", None, 1000);
    f.message(
        "bad",
        "main",
        1100,
        json!({"input":"PRIVATE_INVALID_TOKEN","output":20}),
    );
    f.message("good", "main", 1200, usage(30));
    let mut store = f.store();
    let report = f.scan(&mut store);
    assert_eq!(store.events().unwrap().len(), 1);
    assert_eq!(report.warnings.len(), 1);
    assert!(!report.warnings[0].contains("PRIVATE"));
}

#[test]
fn explicit_root_deduplicates_copied_database_and_retains_deleted_usage() {
    let mut f = Fixture::new();
    f.session("main", None, 1000);
    f.message("msg", "main", 1100, usage(30));
    let mut store = f.store();
    f.scan(&mut store);
    f.source
        .execute_batch("PRAGMA wal_checkpoint(TRUNCATE)")
        .unwrap();
    let copy = f.home.join("custom-opencode");
    fs::create_dir(&copy).unwrap();
    fs::copy(
        f.home.join(".local/share/opencode/opencode.db"),
        copy.join("opencode.db"),
    )
    .unwrap();
    f.config.opencode_root = Some(copy);
    f.scan(&mut store);
    assert_eq!(store.events().unwrap().len(), 1);
    f.config.opencode_root = None;
    f.source.execute("DELETE FROM message", []).unwrap();
    f.scan(&mut store);
    assert_eq!(store.events().unwrap().len(), 1);
}
