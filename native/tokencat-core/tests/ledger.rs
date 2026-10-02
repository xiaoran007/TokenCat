use chrono::{DateTime, TimeZone, Utc};
use rusqlite::Connection;
use serde_json::json;
use std::{
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};
use tokencat_core::{model::*, pricing::PricingCatalog, query::query_dashboard, store::Store};

static NEXT: AtomicU64 = AtomicU64::new(0);
struct Scratch(PathBuf);
impl Scratch {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "tokencat-ledger-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn db(&self) -> PathBuf {
        self.0.join("usage.sqlite3")
    }
}
impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
fn cursor(identity: &str, generation: u64) -> SourceCursor {
    SourceCursor {
        identity: identity.into(),
        path: format!("/{identity}.jsonl"),
        offset: 100,
        length: 100,
        modified_ns: "1".into(),
        head_hash: "hash".into(),
        parser_state: json!({"generation":generation}),
    }
}
fn event(id: &str, session: &str, timestamp: i64) -> UsageEvent {
    UsageEvent {
        id: id.into(),
        provider: Provider::Claude,
        session_id: session.into(),
        timestamp_ms: timestamp,
        model: Some("claude-sonnet-4-6".into()),
        attribution: "explicit".into(),
        incomplete: false,
        tokens: Tokens {
            input_uncached: Some(1000),
            cache_read: Some(5000),
            cache_write: Some(2000),
            cache_write_5m: Some(2000),
            cache_write_1h: Some(0),
            output: Some(100),
            reasoning: Some(60),
            total: Some(8100),
        },
    }
}
fn session(id: &str, parent: Option<&str>) -> SessionMetadata {
    SessionMetadata {
        id: id.into(),
        provider: Provider::Claude,
        parent_id: parent.map(str::to_owned),
        project_path: Some("/private/project".into()),
        title: None,
    }
}
fn timestamp(value: &str) -> i64 {
    DateTime::parse_from_rfc3339(value)
        .unwrap()
        .timestamp_millis()
}
fn query(since: i64, until: i64, timezone: &str) -> Query {
    Query {
        since_ms: since,
        until_ms: until,
        timezone: timezone.into(),
        show_paths: false,
    }
}
fn near(actual: f64, expected: f64) {
    assert!((actual - expected).abs() < 1e-9, "{actual} != {expected}");
}

#[test]
fn replay_and_revision_survive_reopen_and_keep_occurrence_time() {
    let scratch = Scratch::new();
    {
        let store = Store::open(&scratch.db()).unwrap();
        let original = event("message", "task", 1000);
        store
            .commit_source(
                &cursor("first", 0),
                &[session("task", None)],
                &[original.clone()],
                &[],
            )
            .unwrap();
        store
            .commit_source(&cursor("copy", 0), &[], &[original], &[])
            .unwrap();
        let mut revised = event("message", "task", 2000);
        revised.tokens.output = Some(200);
        store
            .commit_source(&cursor("first", 0), &[], &[revised], &[])
            .unwrap();
        assert_eq!(store.events().unwrap().len(), 1);
    }
    let store = Store::open(&scratch.db()).unwrap();
    let events = store.events().unwrap();
    assert_eq!(events[0].timestamp_ms, 1000);
    assert_eq!(events[0].tokens.output, Some(200));
    assert_eq!(store.load_cursor("first").unwrap().unwrap().offset, 100);
}

#[test]
fn rollback_does_not_advance_cursor_or_partially_write_metadata() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    Connection::open(scratch.db()).unwrap().execute_batch("CREATE TRIGGER reject_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'test interruption'); END;").unwrap();
    assert!(store
        .commit_source(
            &cursor("first", 0),
            &[session("task", None)],
            &[event("a", "task", 1)],
            &[]
        )
        .is_err());
    assert!(store.load_cursor("first").unwrap().is_none());
    assert!(store.sessions().unwrap().is_empty());
    assert!(store.events().unwrap().is_empty());
}

#[test]
fn rewritten_and_replaced_sources_do_not_erase_usage_history() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    store
        .commit_source(&cursor("first", 0), &[], &[event("a", "task", 1)], &[])
        .unwrap();
    store
        .commit_source(&cursor("first", 1), &[], &[event("b", "task", 2)], &[])
        .unwrap();
    let mut replacement = cursor("replacement", 0);
    replacement.path = "/first.jsonl".into();
    store
        .commit_source(&replacement, &[], &[event("c", "task", 3)], &[])
        .unwrap();
    assert!(store.load_cursor("first").unwrap().is_none());
    assert_eq!(store.events().unwrap().len(), 3);
}

#[test]
fn stale_copied_root_cannot_undo_newer_usage_revision() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let original = event("message", "task", 1000);
    store
        .commit_source(&cursor("first", 0), &[], &[original.clone()], &[])
        .unwrap();
    let mut revised = event("message", "task", 2000);
    revised.tokens.output = Some(200);
    store
        .commit_source(&cursor("first", 0), &[], &[revised], &[])
        .unwrap();
    store
        .commit_source(&cursor("stale-copy", 0), &[], &[original], &[])
        .unwrap();
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].timestamp_ms, 1000);
    assert_eq!(events[0].tokens.output, Some(200));
}

#[test]
fn unknown_tier_threshold_produces_bounds_and_old_claude_long_context_is_unpriced() {
    let mut catalog = PricingCatalog::load(None).unwrap();
    catalog
        .models
        .get_mut("gpt-6-astra")
        .unwrap()
        .long_context
        .as_mut()
        .unwrap()
        .above_input_tokens = None;
    let mut sample = event("a", "task", 1);
    sample.provider = Provider::Codex;
    sample.model = Some("gpt-6-astra".into());
    let cost = catalog.price(&sample);
    assert!(cost.uncertain);
    assert!(cost.tier_max_extra_units > 0);
    sample.provider = Provider::Claude;
    sample.model = Some("claude-sonnet-4-5".into());
    sample.tokens.input_uncached = Some(200001);
    let cost = catalog.price(&sample);
    assert!(cost.unpriced && cost.uncertain);
    assert_eq!(cost.priced_tokens, 0);
}

#[test]
fn legacy_codex_cache_write_uses_base_input_rate_without_an_additive_fee() {
    let catalog = PricingCatalog::load(None).unwrap();
    let mut sample = event("a", "task", 1);
    sample.provider = Provider::Codex;
    sample.model = Some("gpt-5.4".into());
    let cost = catalog.price(&sample);
    assert!(!cost.unpriced && !cost.uncertain);
    assert_eq!(cost.input_units, 2_500_000 * 1_000_000);
    assert_eq!(cost.write_min_units, 5_000_000 * 1_000_000);
    assert_eq!(cost.write_max_units, 5_000_000 * 1_000_000);
    assert_eq!(cost.priced_tokens, 8100);
    sample.tokens.cache_write_5m = None;
    sample.tokens.cache_write_1h = None;
    let cost = catalog.price(&sample);
    assert_eq!(cost.write_min_units, 5_000_000 * 1_000_000);
    assert_eq!(cost.write_max_units, 5_000_000 * 1_000_000);
    assert!(!cost.uncertain);
}

#[test]
fn custom_unknown_cache_write_rates_are_excluded_from_pricing_coverage() {
    let scratch = Scratch::new();
    let path = scratch.0.join("prices.json");
    let content = json!({"id":"custom","retrieved_at":"2026-10-02","sources":["https://example.test/rates"],"models":{"private-model":{"provider":"codex","rates":{"input":1,"cache_read":0.1,"cache_write_5m":null,"cache_write_1h":null,"output":5}}}});
    std::fs::write(&path, content.to_string()).unwrap();
    let catalog = PricingCatalog::load(Some(&path)).unwrap();
    let mut sample = event("a", "task", 1);
    sample.provider = Provider::Codex;
    sample.model = Some("private-model".into());
    let cost = catalog.price(&sample);
    assert!(cost.unpriced && cost.uncertain);
    assert_eq!(cost.priced_tokens, 6100);
    assert_eq!(cost.total_tokens, 8100);
    assert_eq!(cost.write_min_units, 0);
}

#[test]
fn prices_exclusive_categories_and_does_not_double_charge_reasoning() {
    let catalog = PricingCatalog::load(None).unwrap();
    let cost = catalog.price(&event("a", "task", 1));
    assert!(!cost.uncertain && !cost.unpriced);
    assert_eq!(cost.total_tokens, 8100);
    assert_eq!(cost.priced_tokens, 8100);
    assert_eq!(cost.input_units, 3_000_000 * 1_000_000);
    assert_eq!(cost.read_units, 1_500_000 * 1_000_000);
    assert_eq!(cost.write_min_units, 7_500_000 * 1_000_000);
    assert_eq!(cost.output_units, 1_500_000 * 1_000_000);
}

#[test]
fn unknown_cache_ttl_produces_bounds_and_known_mixed_ttls_are_exact() {
    let catalog = PricingCatalog::load(None).unwrap();
    let mut sample = event("a", "task", 1);
    sample.tokens.cache_write_5m = None;
    sample.tokens.cache_write_1h = None;
    let cost = catalog.price(&sample);
    assert_eq!(cost.write_min_units, 7_500_000 * 1_000_000);
    assert_eq!(cost.write_max_units, 12_000_000 * 1_000_000);
    assert!(cost.uncertain);
    sample.tokens.cache_write_5m = Some(1500);
    sample.tokens.cache_write_1h = Some(500);
    let cost = catalog.price(&sample);
    assert_eq!(cost.write_min_units, 8_625_000 * 1_000_000);
    assert_eq!(cost.write_max_units, 8_625_000 * 1_000_000);
    assert!(!cost.uncertain);
}

#[test]
fn model_names_are_exact_and_provider_scoped() {
    let catalog = PricingCatalog::load(None).unwrap();
    let mut sample = event("a", "task", 1);
    sample.model = Some("claude-sonnet-4-6-unknown-suffix".into());
    let unknown = catalog.price(&sample);
    assert!(unknown.unpriced);
    assert_eq!(unknown.priced_tokens, 0);
    assert_eq!(unknown.input_units, 0);
    sample.model = Some("claude-sonnet-4-6".into());
    sample.provider = Provider::Codex;
    assert!(catalog.price(&sample).unpriced);
}

#[test]
fn custom_catalog_reprices_without_rewriting_events() {
    let scratch = Scratch::new();
    let path = scratch.0.join("prices.json");
    let content = json!({"id":"custom","retrieved_at":"2026-10-02","sources":["https://example.test/rates"],"models":{"claude-sonnet-4-6":{"provider":"claude","rates":{"input":1,"cache_read":0.1,"cache_write_5m":1.25,"cache_write_1h":2,"output":5}}}});
    std::fs::write(&path, content.to_string()).unwrap();
    let catalog = PricingCatalog::load(Some(&path)).unwrap();
    assert_eq!(catalog.id, "custom");
    assert_eq!(
        catalog.price(&event("a", "task", 1)).input_units,
        1_000_000 * 1_000_000
    );
    std::fs::write(&path, "{}").unwrap();
    assert!(PricingCatalog::load(Some(&path)).is_err());
}

#[test]
fn fractional_nanodollars_accumulate_without_rounding_each_event() {
    let scratch = Scratch::new();
    let path = scratch.0.join("prices.json");
    let content = json!({"id":"small-rate","retrieved_at":"2026-10-02","sources":["https://example.test/rates"],"models":{"small-model":{"provider":"codex","rates":{"input":0.0005,"cache_read":0,"cache_write_5m":0,"cache_write_1h":0,"output":0}}}});
    std::fs::write(&path, content.to_string()).unwrap();
    let catalog = PricingCatalog::load(Some(&path)).unwrap();
    let events: Vec<_> = (1..=10)
        .map(|index| {
            let mut sample = event(&format!("small-{index}"), "small", index);
            sample.provider = Provider::Codex;
            sample.model = Some("small-model".into());
            sample.tokens = Tokens {
                input_uncached: Some(1),
                cache_read: Some(0),
                cache_write: Some(0),
                output: Some(0),
                total: Some(1),
                ..Tokens::default()
            };
            sample
        })
        .collect();
    let store = Store::open(&scratch.db()).unwrap();
    store
        .commit_source(&cursor("small", 0), &[], &events, &[])
        .unwrap();
    let dashboard = query_dashboard(&store, &catalog, &query(0, 11, "UTC")).unwrap();
    let cost = &dashboard.summary.cost;
    assert!((cost.input_usd - 5e-9).abs() < 1e-20);
    assert_eq!(cost.input_usd, cost.min_usd);
    assert_eq!(cost.min_usd, cost.max_usd);
    assert_eq!(cost.priced_tokens, 10);
    assert_eq!(cost.unpriced_events, 0);
}

#[test]
fn common_codex_models_and_verified_snapshots_have_complete_cost_coverage() {
    let catalog = PricingCatalog::load(None).unwrap();
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let examples = [
        ("gpt-5.5", 40.5),
        ("gpt-5.6-sol", 29.4),
        ("gpt-5.6-terra", 16.7),
        ("gpt-5.6-luna", 1.67),
        ("gpt-6-sol", 14.7),
        ("gpt-4.1-2025-04-14", 12.5),
        ("gpt-5-2025-08-07", 12.625),
        ("gpt-5.1-2025-11-13", 12.625),
        ("gpt-5.2-codex", 17.675),
        ("gpt-5.1-codex-mini", 2.525),
    ];
    let events: Vec<_> = examples
        .iter()
        .enumerate()
        .map(|(index, (model, _))| {
            let mut sample = event(&format!("model-{index}"), "models", index as i64 + 1);
            sample.provider = Provider::Codex;
            sample.model = Some((*model).into());
            sample.tokens = Tokens {
                input_uncached: Some(1000),
                cache_read: Some(1000),
                cache_write: Some(1000),
                output: Some(1000),
                total: Some(4000),
                ..Tokens::default()
            };
            sample
        })
        .collect();
    store
        .commit_source(&cursor("models", 0), &[], &events, &[])
        .unwrap();
    let dashboard = query_dashboard(&store, &catalog, &query(0, 100, "UTC")).unwrap();
    near(
        dashboard.summary.cost.min_usd,
        examples.iter().map(|(_, rate)| rate / 1000.0).sum(),
    );
    assert_eq!(
        dashboard.summary.cost.min_usd,
        dashboard.summary.cost.max_usd
    );
    assert_eq!(dashboard.summary.cost.priced_tokens, 40000);
    assert_eq!(dashboard.summary.cost.unpriced_events, 0);
    assert_eq!(dashboard.summary.cost.uncertain_events, 0);
    let mut unverified = events[0].clone();
    unverified.model = Some("gpt-5.5-unknown-snapshot".into());
    assert!(catalog.price(&unverified).unpriced);
}

#[test]
fn long_context_threshold_applies_full_request_rate() {
    let catalog = PricingCatalog::load(None).unwrap();
    let mut sample = event("a", "task", 1);
    sample.provider = Provider::Codex;
    sample.model = Some("gpt-5.4".into());
    sample.tokens = Tokens {
        input_uncached: Some(272000),
        cache_read: Some(0),
        cache_write: Some(0),
        output: Some(100),
        ..Tokens::default()
    };
    assert_eq!(catalog.price(&sample).input_units, 680_000_000 * 1_000_000);
    sample.tokens.input_uncached = Some(272001);
    let cost = catalog.price(&sample);
    assert_eq!(cost.input_units, 1_360_005_000 * 1_000_000);
    assert_eq!(cost.output_units, 2_250_000 * 1_000_000);
}

#[test]
fn summaries_preserve_cost_ranges_coverage_and_own_task_usage() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let mut child = event("child", "child", 2000);
    child.tokens.cache_write_5m = None;
    child.tokens.cache_write_1h = None;
    let mut unknown = event("unknown", "parent", 3000);
    unknown.model = Some("private-model".into());
    store
        .commit_source(
            &cursor("first", 0),
            &[session("parent", None), session("child", Some("parent"))],
            &[event("parent", "parent", 1000), child, unknown],
            &[],
        )
        .unwrap();
    let dashboard = query_dashboard(
        &store,
        &PricingCatalog::load(None).unwrap(),
        &query(0, 4000, "UTC"),
    )
    .unwrap();
    near(dashboard.summary.cost.min_usd, 0.027);
    near(dashboard.summary.cost.max_usd, 0.0315);
    assert_eq!(dashboard.summary.cost.unpriced_events, 1);
    assert_eq!(dashboard.summary.cost.uncertain_events, 1);
    assert_eq!(dashboard.summary.cost.priced_tokens, 16200);
    assert_eq!(dashboard.summary.cost.total_tokens, 24300);
    assert_eq!(
        dashboard
            .sessions
            .iter()
            .map(|row| row.summary.event_count)
            .sum::<usize>(),
        3
    );
    assert_eq!(
        dashboard
            .sessions
            .iter()
            .find(|row| row.id == "claude:child")
            .unwrap()
            .parent_id
            .as_deref(),
        Some("claude:parent")
    );
    assert!(dashboard
        .projects
        .iter()
        .all(|row| !row.label.contains("private")));
    assert!(dashboard
        .sessions
        .iter()
        .all(|row| row.label.starts_with("session:")));
}

#[test]
fn local_midnight_boundaries_and_repeated_dst_hours_are_distinct() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let before = timestamp("2026-11-01T03:59:59Z");
    let midnight = timestamp("2026-11-01T04:00:00Z");
    let first = timestamp("2026-11-01T05:15:00Z");
    let second = timestamp("2026-11-01T06:15:00Z");
    let until = timestamp("2026-11-02T05:00:00Z");
    store
        .commit_source(
            &cursor("first", 0),
            &[],
            &[
                event("before", "task", before),
                event("midnight", "task", midnight),
                event("first", "task", first),
                event("second", "task", second),
                event("until", "task", until),
            ],
            &[],
        )
        .unwrap();
    let dashboard = query_dashboard(
        &store,
        &PricingCatalog::load(None).unwrap(),
        &query(midnight, until, "America/New_York"),
    )
    .unwrap();
    assert_eq!(dashboard.summary.event_count, 3);
    assert_eq!(dashboard.timeline.len(), 25);
    assert_eq!(
        dashboard
            .timeline
            .iter()
            .filter(|bucket| bucket.summary.event_count > 0)
            .count(),
        3
    );
    assert!(dashboard.timeline.iter().any(|bucket| bucket.timestamp_ms
        == timestamp("2026-11-01T05:00:00Z")
        && bucket.summary.event_count == 1));
    assert!(dashboard.timeline.iter().any(|bucket| bucket.timestamp_ms
        == timestamp("2026-11-01T06:00:00Z")
        && bucket.summary.event_count == 1));
}

#[test]
fn daily_buckets_follow_local_calendar_and_structural_parent_is_available() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let start = timestamp("2026-10-01T04:00:00Z");
    let until = timestamp("2026-10-08T04:00:00Z");
    store
        .commit_source(
            &cursor("first", 0),
            &[session("parent", None), session("child", Some("parent"))],
            &[event("a", "child", start + 1)],
            &[],
        )
        .unwrap();
    let dashboard = query_dashboard(
        &store,
        &PricingCatalog::load(None).unwrap(),
        &query(start, until, "America/New_York"),
    )
    .unwrap();
    assert_eq!(dashboard.timeline.len(), 7);
    assert_eq!(dashboard.timeline[0].timestamp_ms, start);
    let parent = dashboard
        .sessions
        .iter()
        .find(|row| row.id == "claude:parent")
        .unwrap();
    assert_eq!(parent.summary.event_count, 0);
    assert!(query_dashboard(
        &store,
        &PricingCatalog::load(None).unwrap(),
        &query(start, until, "not-a-zone")
    )
    .is_err());
}

#[test]
fn newest_state_wins_independent_of_source_scan_order() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let mut state = ObservedState {
        provider: Provider::Codex,
        session_id: "task".into(),
        timestamp_ms: Utc
            .with_ymd_and_hms(2026, 10, 2, 12, 0, 0)
            .unwrap()
            .timestamp_millis(),
        kind: "quota".into(),
        data: json!({"used_percent":10}),
    };
    store
        .commit_source(&cursor("first", 0), &[], &[], &[state.clone()])
        .unwrap();
    state.timestamp_ms -= 1000;
    state.data = json!({"used_percent":5});
    store
        .commit_source(&cursor("old", 0), &[], &[], &[state])
        .unwrap();
    assert_eq!(store.states().unwrap()[0].data["used_percent"], 10);
}
