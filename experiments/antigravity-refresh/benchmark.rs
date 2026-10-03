// Appended to the existing synthetic Antigravity fixture helpers by run.py.
use sha2::{Digest, Sha256};
use std::time::Instant;
static PAYLOAD: AtomicU64 = AtomicU64::new(0);
// Darwin clock() reports process CPU time in microseconds.
unsafe extern "C" { fn clock() -> std::ffi::c_long; }
fn cpu_ms() -> f64 {
    assert!(cfg!(target_os = "macos"));
    let ticks = unsafe { clock() };
    assert!(ticks >= 0);
    ticks as f64 / 1000.0
}
fn measure(f: &Fixture, store: &mut Store, profile: &str, scenario: &str, rounds: usize) {
    let mut walls = Vec::new();
    let mut cpus = Vec::new();
    let mut last_report = ScanReport::default();
    for _ in 0..rounds {
        let cpu = cpu_ms();
        let start = Instant::now();
        let report = f.scan(store);
        walls.push(start.elapsed().as_secs_f64() * 1000.0);
        cpus.push(cpu_ms() - cpu);
        assert!(report.warnings.is_empty(), "{:?}", report.warnings);
        last_report = report;
    }
    walls.sort_by(f64::total_cmp);
    cpus.sort_by(f64::total_cmp);
    let events = store.events().unwrap();
    let digest = format!("{:x}", Sha256::digest(serde_json::to_vec(&serde_json::json!({
        "events": events, "sessions": store.sessions().unwrap(), "report": last_report
    })).unwrap()));
    println!("{}", serde_json::json!({"profile":profile,"scenario":scenario,"rounds":rounds,
        "wall_ms_median":walls[rounds/2],"cpu_ms_median":cpus[rounds/2],
        "wall_ms_min":walls[0],"wall_ms_max":walls[rounds-1],
        "events":events.len(),"digest":digest}));
}
fn main() {
    let profile = std::env::args().nth(1).unwrap();
    let (databases, generations, payload) = match profile.as_str() {
        "small" => (4, 20, 4096),
        "large" => (8, 80, 262144),
        _ => panic!("unknown profile"),
    };
    PAYLOAD.store(payload, Ordering::Relaxed);
    let f = Fixture::new();
    let writers: Vec<_> = (0..databases).map(|session| {
        let db = f.source("antigravity", &format!("session-{session}"));
        db.execute_batch("BEGIN").unwrap();
        for index in 0..generations {
            let request = format!("request-{session}-{index}");
            insert_gen(&db, index, &generation(&counters(Some(&request), 1000, 100, 50), Some("gpt-5"), Some(TIME + index), &[]));
        }
        db.execute_batch("COMMIT").unwrap();
        db
    }).collect();
    let mut store = f.store();
    measure(&f, &mut store, &profile, "cold", 1);
    assert_eq!(store.events().unwrap().len(), (databases * generations) as usize);
    measure(&f, &mut store, &profile, "unchanged", 9);
    let before = serde_json::to_vec(&store.events().unwrap()).unwrap();
    // Change a historical row, not just an append; keep its usage ID stable.
    insert_gen(&writers[0], 0, &generation(&counters(Some("request-0-0"), 2000, 100, 50), Some("gpt-5"), Some(TIME), &[]));
    measure(&f, &mut store, &profile, "wal_update", 1);
    assert_ne!(serde_json::to_vec(&store.events().unwrap()).unwrap(), before);
    insert_gen(&writers[0], generations, &generation(&counters(Some("request-new"), 3000, 100, 50), Some("gpt-5"), Some(TIME + generations), &[]));
    measure(&f, &mut store, &profile, "wal_append", 1);
    assert_eq!(store.events().unwrap().len(), (databases * generations + 1) as usize);
    writers[0].execute_batch("PRAGMA wal_checkpoint(TRUNCATE)").unwrap();
    measure(&f, &mut store, &profile, "checkpoint", 1);
    measure(&f, &mut store, &profile, "unchanged_after_writes", 9);
    // Atomic replacement, with a new inode and a different usage record.
    let old = f.home.join(".gemini/antigravity/conversations/session-0.db");
    let replacement = f.home.join("replacement.db");
    let db = Connection::open(&replacement).unwrap();
    db.execute_batch("CREATE TABLE gen_metadata(idx INTEGER PRIMARY KEY,data BLOB,size INTEGER);").unwrap();
    insert_gen(&db, 0, &generation(&counters(Some("replacement-request"), 4000, 100, 50), Some("gpt-5"), Some(TIME), &[]));
    drop(db);
    drop(writers);
    fs::rename(replacement, old).unwrap();
    let before = serde_json::to_vec(&store.events().unwrap()).unwrap();
    measure(&f, &mut store, &profile, "replacement", 1);
    assert_ne!(serde_json::to_vec(&store.events().unwrap()).unwrap(), before);
}
