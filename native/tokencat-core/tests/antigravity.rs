use rusqlite::{params, Connection};
use std::{
    cell::RefCell,
    fs,
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};
use tokencat_core::{antigravity::Cache, model::*, store::Store};

static NEXT: AtomicU64 = AtomicU64::new(0);
const TIME: i64 = 1_790_928_000_123;
struct Fixture {
    home: PathBuf,
    config: CoreConfig,
    cache: RefCell<Cache>,
}
impl Fixture {
    fn new() -> Self {
        let home = std::env::temp_dir().join(format!(
            "tokencat-antigravity-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&home).unwrap();
        let config = CoreConfig {
            home: home.clone(),
            database_path: home.join("usage.sqlite"),
            codex_root: None,
            claude_roots: vec![],
            opencode_root: None,
            antigravity_roots: vec![],
            pricing_path: None,
        };
        Self { home, config, cache: RefCell::new(Cache::default()) }
    }
    fn source(&self, root: &str, session: &str) -> Connection {
        let path = self
            .home
            .join(format!(".gemini/{root}/conversations/{session}.db"));
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        let db = Connection::open(path).unwrap();
        db.execute_batch(
            "PRAGMA journal_mode=WAL;
            CREATE TABLE gen_metadata(idx INTEGER PRIMARY KEY,data BLOB,size INTEGER);
            CREATE TABLE steps(idx INTEGER PRIMARY KEY,metadata BLOB,step_payload BLOB);",
        )
        .unwrap();
        db
    }
    fn store(&self) -> Store {
        Store::open(&self.config.database_path).unwrap()
    }
    fn scan(&self, store: &mut Store) -> ScanReport {
        let mut report = ScanReport::default();
        self.cache.borrow_mut().collect(store, &self.config, &mut report).unwrap();
        report
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.home);
    }
}
fn varint(mut value: u64) -> Vec<u8> {
    let mut output = Vec::new();
    loop {
        let byte = (value & 127) as u8;
        value >>= 7;
        output.push(byte | if value == 0 { 0 } else { 128 });
        if value == 0 {
            break;
        }
    }
    output
}
fn number(tag: u32, value: u64) -> Vec<u8> {
    [varint(u64::from(tag) << 3), varint(value)].concat()
}
fn bytes(tag: u32, data: &[u8]) -> Vec<u8> {
    [
        varint((u64::from(tag) << 3) | 2),
        varint(data.len() as u64),
        data.to_vec(),
    ]
    .concat()
}
fn timestamp(tag: u32, ms: i64) -> Vec<u8> {
    bytes(
        tag,
        &[
            number(1, (ms / 1000) as u64),
            number(2, (ms % 1000) as u64 * 1_000_000),
        ]
        .concat(),
    )
}
fn counters(request: Option<&str>, input: u64, cache: u64, output: u64) -> Vec<u8> {
    let mut fields = vec![
        number(1, 1234),
        number(2, input),
        number(3, output),
        number(5, cache),
        number(6, 24),
        number(9, output / 2),
        number(10, output - output / 2),
    ];
    if let Some(request) = request {
        fields.push(bytes(11, request.as_bytes()));
    }
    fields.concat()
}
fn generation(usage: &[u8], model: Option<&str>, time: Option<i64>, steps: &[u64]) -> Vec<u8> {
    let mut chat = vec![
        bytes(1, b"PRIVATE PROMPT SENTINEL"),
        bytes(2, b"PRIVATE RESPONSE SENTINEL"),
        bytes(4, usage),
    ];
    if let Some(model) = model {
        chat.push(bytes(19, model.as_bytes()));
    }
    if let Some(time) = time {
        chat.push(bytes(9, &timestamp(4, time)));
    }
    let indices = steps
        .iter()
        .flat_map(|idx| varint(*idx))
        .collect::<Vec<_>>();
    [bytes(2, &indices), bytes(1, &chat.concat())].concat()
}
fn step(usage: &[u8], start: Option<i64>, complete: Option<i64>, model: Option<&str>) -> Vec<u8> {
    let mut fields = vec![bytes(4, b"PRIVATE TOOL ARGUMENT SENTINEL"), bytes(9, usage)];
    if let Some(time) = start {
        fields.push(timestamp(32, time));
        fields.push(timestamp(1, time - 2));
    }
    if let Some(time) = complete {
        fields.push(timestamp(8, time));
    }
    if let Some(model) = model {
        fields.push(bytes(24, &bytes(8, model.as_bytes())));
    }
    fields.concat()
}
fn insert_gen(db: &Connection, idx: i64, data: &[u8]) {
    db.execute(
        "INSERT OR REPLACE INTO gen_metadata(idx,data,size) VALUES(?1,?2,?3)",
        params![idx, data, data.len()],
    )
    .unwrap();
}
fn insert_step(db: &Connection, idx: i64, metadata: &[u8]) {
    db.execute(
        "INSERT OR REPLACE INTO steps(idx,metadata,step_payload) VALUES(?1,?2,?3)",
        params![idx, metadata, b"PRIVATE STEP BODY".as_slice()],
    )
    .unwrap();
}
fn insert_session(db: &Connection, parent: Option<&str>, uris: &[&str]) {
    db.execute_batch(
        "CREATE TABLE IF NOT EXISTS trajectory_metadata_blob(id TEXT PRIMARY KEY,data BLOB)",
    )
    .unwrap();
    let mut fields = vec![
        bytes(4, b"PRIVATE AGENT SCRIPT"),
        bytes(10, b"PRIVATE STATIC CONFIG"),
    ];
    if let Some(parent) = parent {
        fields.push(bytes(5, parent.as_bytes()));
    }
    fields.extend(uris.iter().map(|uri| bytes(7, uri.as_bytes())));
    db.execute(
        "INSERT OR REPLACE INTO trajectory_metadata_blob(id,data) VALUES('main',?1)",
        [fields.concat()],
    )
    .unwrap();
}

#[test]
fn concurrent_wal_appends_are_complete_after_writer_finishes() {
    let f = Fixture::new();
    let db = f.source("antigravity", "concurrent");
    let mut store = f.store();
    f.scan(&mut store);
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let writer_barrier = barrier.clone();
    let writer = std::thread::spawn(move || {
        writer_barrier.wait();
        for index in 0..50 {
            let request = format!("concurrent-{index}");
            insert_gen(&db, index, &generation(
                &counters(Some(&request), 100, 0, 20),
                Some("gemini-2.5-pro"), Some(TIME + index), &[],
            ));
        }
    });
    barrier.wait();
    while !writer.is_finished() {
        assert!(f.scan(&mut store).warnings.is_empty());
    }
    writer.join().unwrap();
    assert!(f.scan(&mut store).warnings.is_empty());
    assert_eq!(store.events().unwrap().len(), 50);
    assert_eq!(f.scan(&mut store).events_upserted, 0);
}

#[test]
fn enums_are_not_tokens_and_thinking_is_an_output_subset() {
    let f = Fixture::new();
    let db = f.source("antigravity", "one");
    let mut store = f.store();
    insert_gen(
        &db,
        0,
        &generation(
            &counters(Some("request-1"), 100, 900, 80),
            Some("gemini-2.5-pro"),
            Some(TIME),
            &[],
        ),
    );
    let report = f.scan(&mut store);
    assert!(report.warnings.is_empty());
    let event = store.events().unwrap().pop().unwrap();
    assert_eq!(event.tokens.input_uncached, Some(100));
    assert_eq!(event.tokens.cache_read, Some(900));
    assert_eq!(event.tokens.output, Some(80));
    assert_eq!(event.tokens.reasoning, Some(40));
    assert_eq!(event.tokens.total, Some(1080));
    assert_eq!(event.model_provider.as_deref(), Some("gemini"));
    assert_eq!(event.timestamp_ms, TIME);
    assert!(!event.incomplete);
}
#[test]
fn generations_without_timestamps_use_their_linked_step_start() {
    let f = Fixture::new();
    let db = f.source("antigravity", "one");
    let mut store = f.store();
    let usage = counters(Some("request-2"), 100, 900, 80);
    insert_gen(
        &db,
        0,
        &generation(&usage, Some("gemini-2.5-pro"), None, &[12]),
    );
    insert_step(&db, 12, &step(&usage, Some(TIME), Some(TIME + 3000), None));
    let report = f.scan(&mut store);
    assert!(report.warnings.is_empty());
    assert_eq!(report.events_upserted, 1);
    assert_eq!(report.undated_events, 0);
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].timestamp_ms, TIME);
}
#[test]
fn interrupted_step_usage_is_ingested_and_later_generation_is_deduplicated() {
    let f = Fixture::new();
    let db = f.source("antigravity-cli", "one");
    let mut store = f.store();
    let usage = counters(Some("request-3"), 50, 0, 20);
    insert_step(&db, 8, &step(&usage, Some(TIME), Some(TIME + 3000), None));
    f.scan(&mut store);
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert!(events[0].model.is_none());
    insert_gen(
        &db,
        0,
        &generation(&usage, Some("gemini-2.5-flash"), None, &[8]),
    );
    f.scan(&mut store);
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].model.as_deref(), Some("gemini-2.5-flash"));
}
#[test]
fn undated_requests_are_reported_without_being_assigned_to_mtime_or_today() {
    let f = Fixture::new();
    let db = f.source("antigravity", "one");
    let mut store = f.store();
    let usage = counters(Some("undated"), 50, 300, 20);
    insert_gen(
        &db,
        0,
        &generation(&usage, Some("gemini-2.5-flash"), None, &[8]),
    );
    for _ in 0..2 {
        let report = f.scan(&mut store);
        assert_eq!(report.undated_events, 1);
        assert_eq!(report.undated_tokens, 370);
        assert!(store.events().unwrap().is_empty());
    }
    insert_step(&db, 8, &step(&usage, Some(TIME), None, None));
    let report = f.scan(&mut store);
    assert_eq!(report.undated_events, 0);
    assert_eq!(store.events().unwrap()[0].timestamp_ms, TIME);
}
#[test]
fn app_cli_copies_merge_and_live_wal_updates_are_observed() {
    let f = Fixture::new();
    let app = f.source("antigravity", "one");
    let cli = f.source("antigravity-cli", "one");
    let mut store = f.store();
    let original = generation(
        &counters(Some("same-request"), 100, 500, 20),
        Some("gemini-2.5-pro"),
        Some(TIME),
        &[],
    );
    insert_gen(&app, 0, &original);
    insert_gen(&cli, 0, &original);
    let report = f.scan(&mut store);
    assert_eq!(report.files_discovered, 2);
    assert_eq!(report.events_upserted, 1);
    assert_eq!(f.scan(&mut store).files_changed, 0);
    // Connections stay open: new data is in the WAL, not the main DB mtime.
    insert_gen(
        &app,
        0,
        &generation(
            &counters(Some("same-request"), 100, 500, 80),
            Some("gemini-2.5-pro"),
            Some(TIME),
            &[],
        ),
    );
    let report = f.scan(&mut store);
    assert_eq!(report.files_changed, 1);
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].tokens.total, Some(680));
    assert_eq!(f.scan(&mut store).events_upserted, 0);
}
#[test]
fn an_older_replica_cannot_replace_a_finished_request() {
    let f = Fixture::new();
    let app = f.source("antigravity", "one");
    let cli = f.source("antigravity-cli", "one");
    let mut store = f.store();
    let final_usage = counters(Some("revised-request"), 100, 500, 80);
    insert_step(
        &app,
        8,
        &step(&final_usage, Some(TIME), Some(TIME + 5000), None),
    );
    insert_gen(
        &app,
        0,
        &generation(&final_usage, Some("gemini-2.5-pro"), None, &[8]),
    );
    f.scan(&mut store);
    drop(app);
    fs::remove_file(f.home.join(".gemini/antigravity/conversations/one.db")).unwrap();
    let partial_usage = counters(Some("revised-request"), 100, 500, 20);
    insert_step(
        &cli,
        8,
        &step(&partial_usage, Some(TIME), Some(TIME + 1000), None),
    );
    insert_gen(
        &cli,
        0,
        &generation(&partial_usage, Some("gemini-2.5-pro"), None, &[8]),
    );
    f.scan(&mut store);
    let event = store.events().unwrap().pop().unwrap();
    assert_eq!(event.tokens.total, Some(680));
    assert_eq!(event.timestamp_ms, TIME);
    assert_eq!(event.revision_ms, Some(TIME + 5000));
}
#[test]
fn missing_ids_use_linked_step_identity_across_flush() {
    let f = Fixture::new();
    let db = f.source("antigravity", "one");
    let mut store = f.store();
    let usage = counters(None, 80, 0, 30);
    insert_step(&db, 7, &step(&usage, Some(TIME), None, None));
    f.scan(&mut store);
    insert_gen(
        &db,
        0,
        &generation(&usage, Some("gemini-2.5-flash"), None, &[7]),
    );
    f.scan(&mut store);
    assert_eq!(store.events().unwrap().len(), 1);
}
#[test]
fn response_id_arriving_after_restart_preserves_the_original_event() {
    let f = Fixture::new();
    let db = f.source("antigravity", "one");
    insert_step(
        &db,
        7,
        &step(&counters(None, 80, 0, 30), Some(TIME), None, None),
    );
    let original_id = {
        let mut store = f.store();
        f.scan(&mut store);
        store.events().unwrap()[0].id.clone()
    };
    let final_usage = counters(Some("request-final"), 80, 0, 40);
    insert_step(
        &db,
        7,
        &step(&final_usage, Some(TIME), Some(TIME + 1000), None),
    );
    insert_gen(
        &db,
        0,
        &generation(&final_usage, Some("gemini-2.5-flash"), None, &[7]),
    );
    let mut store = f.store();
    f.scan(&mut store);
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].id, original_id);
    assert_eq!(events[0].tokens.total, Some(120));
    assert_eq!(f.scan(&mut store).events_upserted, 0);
}
#[test]
fn a_generation_flushed_before_its_step_keeps_its_identity() {
    let f = Fixture::new();
    let db = f.source("antigravity", "one");
    let mut store = f.store();
    insert_gen(
        &db,
        0,
        &generation(
            &counters(None, 80, 0, 30),
            Some("gemini-2.5-flash"),
            Some(TIME),
            &[7],
        ),
    );
    f.scan(&mut store);
    let original_id = store.events().unwrap()[0].id.clone();
    insert_step(
        &db,
        7,
        &step(
            &counters(Some("request-later"), 80, 0, 40),
            Some(TIME),
            Some(TIME + 1000),
            None,
        ),
    );
    f.scan(&mut store);
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].id, original_id);
    assert_eq!(events[0].tokens.total, Some(120));
}
#[test]
fn a_new_request_id_merges_previously_unidentified_copies() {
    let f = Fixture::new();
    let app = f.source("antigravity", "one");
    let cli = f.source("antigravity-cli", "copy");
    let partial = step(&counters(None, 80, 0, 30), Some(TIME), None, None);
    insert_step(&app, 7, &partial);
    insert_step(&cli, 7, &partial);
    {
        let mut store = f.store();
        f.scan(&mut store);
        // Without a shared session or request identifier these cannot yet be
        // proven to be copies. The later response ID supplies that evidence.
        assert_eq!(store.events().unwrap().len(), 2);
    }
    let final_usage = counters(Some("request-copy"), 80, 0, 40);
    let completed = step(&final_usage, Some(TIME), Some(TIME + 1000), None);
    insert_step(&app, 7, &completed);
    insert_step(&cli, 7, &completed);
    insert_gen(
        &app,
        0,
        &generation(&final_usage, Some("gemini-2.5-flash"), None, &[7]),
    );
    {
        let mut store = f.store();
        f.scan(&mut store);
        let events = store.events().unwrap();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].tokens.total, Some(120));
    }
    drop(app);
    fs::remove_file(f.home.join(".gemini/antigravity/conversations/one.db")).unwrap();
    let mut store = f.store();
    f.scan(&mut store);
    assert_eq!(store.events().unwrap().len(), 1);
    insert_step(
        &cli,
        7,
        &step(
            &counters(Some("request-copy"), 80, 0, 50),
            Some(TIME),
            Some(TIME + 2000),
            None,
        ),
    );
    f.scan(&mut store);
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].tokens.total, Some(130));
}
#[test]
fn a_linked_completed_step_can_finish_a_partial_generation_snapshot() {
    let f = Fixture::new();
    let db = f.source("antigravity", "one");
    let mut store = f.store();
    insert_gen(
        &db,
        0,
        &generation(
            &counters(None, 80, 300, 10),
            Some("gemini-2.5-flash"),
            None,
            &[7],
        ),
    );
    insert_step(
        &db,
        7,
        &step(
            &counters(Some("completed-step"), 80, 300, 30),
            Some(TIME),
            Some(TIME + 1000),
            None,
        ),
    );
    let report = f.scan(&mut store);
    assert_eq!(report.undated_events, 0);
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].tokens.total, Some(410));
    assert_eq!(events[0].timestamp_ms, TIME);
}
#[test]
fn missing_model_stays_unknown_and_cache_write_ttl_stays_unknown() {
    let f = Fixture::new();
    let db = f.source("antigravity", "one");
    let mut store = f.store();
    let usage = [counters(Some("cache-write"), 100, 0, 20), number(4, 300)].concat();
    insert_gen(&db, 0, &generation(&usage, None, Some(TIME), &[]));
    f.scan(&mut store);
    let event = store.events().unwrap().pop().unwrap();
    assert!(event.model.is_none());
    assert_eq!(event.attribution, "unattributed");
    assert_eq!(event.tokens.total, Some(420));
    assert_eq!(event.tokens.cache_write, Some(300));
    assert_eq!(event.tokens.cache_write_5m, None);
    assert_eq!(event.tokens.cache_write_1h, None);
}
#[test]
fn contradictory_output_breakdown_is_marked_incomplete() {
    let f = Fixture::new();
    let db = f.source("antigravity", "one");
    let mut store = f.store();
    let usage = [counters(Some("bad-parts"), 100, 0, 20), number(9, 30)].concat();
    insert_gen(
        &db,
        0,
        &generation(&usage, Some("gemini-2.5-pro"), Some(TIME), &[]),
    );
    f.scan(&mut store);
    let event = store.events().unwrap().pop().unwrap();
    assert!(event.incomplete);
    assert_eq!(event.tokens.reasoning, None);
    assert_eq!(event.tokens.output, Some(20));
}
fn has_secret(path: &Path) -> bool {
    fs::read(path).is_ok_and(|bytes| bytes.windows(7).any(|window| window == b"PRIVATE"))
}
#[test]
fn bodies_are_excluded_and_malformed_metadata_does_not_leak_to_warnings() {
    let f = Fixture::new();
    let db = f.source("antigravity", "one");
    let mut store = f.store();
    let usage = [
        counters(Some("safe"), 100, 900, 80),
        bytes(8, b"PRIVATE RESPONSE HEADERS"),
    ]
    .concat();
    insert_session(&db, Some("parent-session"), &["file:///developer/project"]);
    insert_gen(
        &db,
        0,
        &generation(&usage, Some("gemini-2.5-pro"), None, &[12]),
    );
    insert_step(&db, 12, &step(&usage, Some(TIME), None, None));
    insert_gen(
        &db,
        1,
        &[10, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255],
    );
    let report = f.scan(&mut store);
    assert_eq!(report.warnings.len(), 1);
    assert!(!serde_json::to_string(&report).unwrap().contains("PRIVATE"));
    assert!(!serde_json::to_string(&store.events().unwrap())
        .unwrap()
        .contains("PRIVATE"));
    assert!(!has_secret(&f.config.database_path));
    assert!(!has_secret(&f.home.join("usage.sqlite-wal")));
}

#[test]
fn session_metadata_attributes_project_and_parent_without_reading_scripts() {
    let f = Fixture::new();
    let db = f.source("antigravity", "child");
    let mut store = f.store();
    insert_session(&db, Some("parent"), &["file:///developer/My%20Project"]);
    insert_gen(
        &db,
        0,
        &generation(
            &counters(Some("child-request"), 10, 0, 2),
            Some("gemini-2.5-pro"),
            Some(TIME),
            &[],
        ),
    );
    f.scan(&mut store);
    let session = store.sessions().unwrap().pop().unwrap();
    assert_eq!(session.id, "child");
    assert_eq!(session.parent_id.as_deref(), Some("parent"));
    assert_eq!(
        session.project_path.as_deref(),
        Some("/developer/My Project")
    );
    assert!(session.title.is_none());
    // Metadata changes also invalidate the projected snapshot digest.
    insert_session(
        &db,
        Some("parent"),
        &["file://localhost/developer/New%20Project"],
    );
    assert_eq!(f.scan(&mut store).files_changed, 1);
    assert_eq!(
        store.sessions().unwrap()[0].project_path.as_deref(),
        Some("/developer/New Project")
    );
}

#[test]
fn multiple_workspaces_and_remote_uris_do_not_get_an_arbitrary_project() {
    let f = Fixture::new();
    let db = f.source("antigravity", "one");
    let mut store = f.store();
    insert_session(
        &db,
        Some("one"),
        &["file:///developer/one", "file:///developer/two"],
    );
    insert_gen(
        &db,
        0,
        &generation(
            &counters(Some("multi-project"), 10, 0, 2),
            Some("gemini-2.5-pro"),
            Some(TIME),
            &[],
        ),
    );
    f.scan(&mut store);
    let session = store.sessions().unwrap().pop().unwrap();
    assert!(session.parent_id.is_none());
    assert!(session.project_path.is_none());
    insert_session(&db, None, &["vscode-remote://ssh-remote/server/project"]);
    f.scan(&mut store);
    assert!(store.sessions().unwrap()[0].project_path.is_none());
    insert_session(
        &db,
        None,
        &[
            "file:///developer/local",
            "vscode-remote://ssh-remote/server/project",
        ],
    );
    f.scan(&mut store);
    assert!(store.sessions().unwrap()[0].project_path.is_none());
}
