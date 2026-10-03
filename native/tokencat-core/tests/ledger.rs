use chrono::{DateTime, TimeZone, Utc};
use rusqlite::Connection;
use serde_json::json;
use std::{
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};
use tokencat_core::{model::*, pricing::PricingCatalog, query::query_dashboard, store::Store};

// Deterministic math regression fixture, independent of live LiteLLM updates.
fn legacy_catalog() -> PricingCatalog {
    PricingCatalog::from_json(include_str!("fixtures/legacy-pricing.json"), "2026-10-02").unwrap()
}

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
        uncertain_time: None,
        id: id.into(),
        provider: Provider::Claude,
        session_id: session.into(),
        timestamp_ms: timestamp,
        model: Some("claude-sonnet-4-6".into()),
        model_provider: None,
        revision_ms: None,
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
        providers: None,
        granularity: TimelineGranularity::Auto,
        include_details: false,
    }
}
fn near(actual: f64, expected: f64) {
    assert!((actual - expected).abs() < 1e-9, "{actual} != {expected}");
}

#[test]
fn old_query_json_keeps_auto_buckets_and_omits_unrequested_details() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    store.commit_source(&cursor("first", 0), &[], &[event("a", "task", 1000)], &[]).unwrap();
    let old: Query = serde_json::from_value(json!({
        "since_ms": 0, "until_ms": 86_400_000, "timezone": "UTC", "show_paths": false
    })).unwrap();
    assert_eq!(old.granularity, TimelineGranularity::Auto);
    assert_eq!(old.providers, None);
    assert!(!old.include_details);
    let dashboard = query_dashboard(&store, &legacy_catalog(), &old).unwrap();
    assert_eq!(dashboard.schema_version, 1);
    assert_eq!(dashboard.timeline.len(), 24);
    let json = serde_json::to_value(&dashboard).unwrap();
    assert!(json["timeline"].as_array().unwrap().iter().all(|bucket| bucket.get("details").is_none()));
    for field in ["providers", "models", "projects", "sessions"] {
        assert!(json[field].as_array().unwrap().iter().all(|row| row.get("primary_model").is_none()));
    }
    let long = query_dashboard(&store, &legacy_catalog(), &query(0, 4 * 86_400_000, "UTC")).unwrap();
    assert_eq!(long.timeline.len(), 4);
}

#[test]
fn provider_filter_applies_before_all_aggregates_and_filters_observed_states() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let mut codex = event("codex", "same-id", 2000);
    codex.provider = Provider::Codex;
    codex.model = Some("private-model".into());
    let mut codex_session = session("same-id", None);
    codex_session.provider = Provider::Codex;
    codex_session.project_path = Some("/other/project".into());
    let states = [Provider::Claude, Provider::Codex].map(|provider| ObservedState {
        provider, session_id: "same-id".into(), timestamp_ms: 1000,
        kind: "quota".into(), data: json!({"percent": 40}),
    });
    store.commit_source(&cursor("first", 0), &[session("same-id", None), codex_session],
        &[event("claude", "same-id", 1000), codex], &states).unwrap();
    let mut request = query(0, 4000, "UTC");
    request.providers = Some(vec![Provider::Claude, Provider::Claude]);
    request.include_details = true;
    let dashboard = query_dashboard(&store, &legacy_catalog(), &request).unwrap();
    assert_eq!(dashboard.summary.event_count, 1);
    assert_eq!(dashboard.summary.cost.total_tokens, 8100);
    assert!(dashboard.summary.cost.unknown_models.is_empty());
    assert_eq!(dashboard.providers.len(), 1);
    assert_eq!(dashboard.providers[0].provider, Some(Provider::Claude));
    assert_eq!(dashboard.models.len(), 1);
    assert_eq!(dashboard.models[0].id, "claude-sonnet-4-6");
    assert_eq!(dashboard.projects.len(), 1);
    assert_eq!(dashboard.sessions.len(), 1);
    assert_eq!(dashboard.sessions[0].id, "claude:same-id");
    assert_eq!(dashboard.states.len(), 1);
    assert_eq!(dashboard.states[0].provider, Provider::Claude);
    let details = dashboard.timeline[0].details.as_ref().unwrap();
    assert_eq!(details.session_count, 1);
    assert_eq!(details.models.len(), 1);
    assert_eq!(details.models[0].provider, Some(Provider::Claude));

    request.providers = Some(vec![]);
    let empty = query_dashboard(&store, &legacy_catalog(), &request).unwrap();
    assert_eq!(empty.summary.event_count, 0);
    assert!(empty.providers.is_empty() && empty.models.is_empty() && empty.projects.is_empty());
    assert!(empty.sessions.is_empty() && empty.states.is_empty());
    assert_eq!(empty.timeline[0].details.as_ref().unwrap().session_count, 0);
    assert!(empty.timeline[0].details.as_ref().unwrap().models.is_empty());
}

#[test]
fn detailed_buckets_deduplicate_sessions_and_preserve_harnesses_and_cost_ranges() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let start = timestamp("2026-10-05T00:00:00Z");
    let until = timestamp("2026-10-12T00:00:00Z");
    let mut other_harness = event("codex", "task", start + 3);
    other_harness.provider = Provider::Codex;
    let mut other_model = event("private", "task", start + 86_400_000);
    other_model.model = Some("private-model".into());
    let mut child = event("child", "child", start + 86_400_001);
    child.tokens.cache_write_5m = None;
    child.tokens.cache_write_1h = None;
    store.commit_source(&cursor("first", 0), &[session("parent", None),
        session("task", Some("parent")), session("child", Some("parent"))], &[
        event("a", "task", start + 1), event("b", "task", start + 2),
        other_harness, other_model, child, event("outside", "task", until),
    ], &[]).unwrap();
    let mut request = query(start, until, "UTC");
    request.granularity = TimelineGranularity::Week;
    let plain = query_dashboard(&store, &legacy_catalog(), &request).unwrap();
    request.include_details = true;
    let detailed = query_dashboard(&store, &legacy_catalog(), &request).unwrap();
    assert_eq!(serde_json::to_value(&plain.summary).unwrap(), serde_json::to_value(&detailed.summary).unwrap());
    assert_eq!(detailed.timeline.len(), 1);
    assert_eq!(detailed.summary.event_count, 5);
    assert_eq!(detailed.summary.cost.total_tokens, 40500);
    assert_eq!(detailed.summary.output_tokens, 500);
    assert_eq!(detailed.summary.reasoning_tokens, 300);
    let bucket = &detailed.timeline[0];
    let details = bucket.details.as_ref().unwrap();
    assert_eq!(details.session_count, 3); // Claude task, Codex task, child; no structural parent.
    assert_eq!(details.models.len(), 3);
    assert_eq!(details.models.iter().map(|row| row.summary.event_count).sum::<usize>(), 5);
    near(details.models.iter().map(|row| row.summary.cost.min_usd).sum(), bucket.summary.cost.min_usd);
    near(details.models.iter().map(|row| row.summary.cost.max_usd).sum(), bucket.summary.cost.max_usd);
    assert!(bucket.summary.cost.max_usd > bucket.summary.cost.min_usd);
    assert_eq!(bucket.summary.cost.unpriced_events, 1);
    assert_eq!(bucket.summary.cost.uncertain_events, 1);
    assert_eq!(details.models.iter().filter(|row| row.label == "claude-sonnet-4-6").count(), 2);
    let task = detailed.sessions.iter().find(|row| row.id == "claude:task").unwrap();
    assert_eq!(task.primary_model.as_deref(), Some("claude-sonnet-4-6"));
    let parent = detailed.sessions.iter().find(|row| row.id == "claude:parent").unwrap();
    assert_eq!(parent.summary.event_count, 0);
    assert_eq!(parent.primary_model, None);
}

#[test]
fn primary_model_uses_window_tokens_with_deterministic_ties_and_unknowns() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let mut a = event("a", "tie", 1000);
    a.model = Some("a-model".into());
    let mut z = event("z", "tie", 2000);
    z.model = Some("z-model".into());
    let mut unknown = event("unknown", "unknown", 1000);
    unknown.model = None;
    unknown.tokens.total = Some(20000);
    let known = event("known", "unknown", 2000);
    store.commit_source(&cursor("first", 0), &[], &[a, z, unknown, known], &[]).unwrap();
    let mut request = query(0, 3000, "UTC");
    request.include_details = true;
    let dashboard = query_dashboard(&store, &legacy_catalog(), &request).unwrap();
    assert_eq!(dashboard.sessions.iter().find(|row| row.id == "claude:tie").unwrap()
        .primary_model.as_deref(), Some("a-model"));
    assert_eq!(dashboard.sessions.iter().find(|row| row.id == "claude:unknown").unwrap().primary_model, None);
    request.since_ms = 2000;
    let latest = query_dashboard(&store, &legacy_catalog(), &request).unwrap();
    assert_eq!(latest.sessions.iter().find(|row| row.id == "claude:tie").unwrap()
        .primary_model.as_deref(), Some("z-model"));
    assert_eq!(latest.sessions.iter().find(|row| row.id == "claude:unknown").unwrap()
        .primary_model.as_deref(), Some("claude-sonnet-4-6"));
}

#[test]
fn explicit_days_keep_local_midnight_across_dst_in_a_short_window() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let start = timestamp("2026-11-01T04:00:00Z");
    let until = timestamp("2026-11-03T05:00:00Z");
    store.commit_source(&cursor("first", 0), &[], &[
        event("first", "task", timestamp("2026-11-01T05:15:00Z")),
        event("repeated", "task", timestamp("2026-11-01T06:15:00Z")),
        event("next", "task", timestamp("2026-11-02T05:00:00Z")),
    ], &[]).unwrap();
    let mut request = query(start, until, "America/New_York");
    request.granularity = TimelineGranularity::Day;
    request.include_details = true;
    let dashboard = query_dashboard(&store, &legacy_catalog(), &request).unwrap();
    assert_eq!(dashboard.timeline.iter().map(|bucket| bucket.timestamp_ms).collect::<Vec<_>>(),
        vec![start, timestamp("2026-11-02T05:00:00Z")]);
    assert_eq!(dashboard.timeline[0].summary.event_count, 2);
    assert_eq!(dashboard.timeline[0].details.as_ref().unwrap().session_count, 1);
    request.granularity = TimelineGranularity::Hour;
    assert_eq!(query_dashboard(&store, &legacy_catalog(), &request).unwrap().timeline.len(), 49);
}

#[test]
fn weeks_start_on_local_monday_and_keep_partial_buckets_across_dst() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let start = timestamp("2026-10-28T04:00:00Z");
    let until = timestamp("2026-11-10T05:00:00Z");
    store.commit_source(&cursor("first", 0), &[], &[
        event("outside-start", "task", start - 1),
        event("a", "task", start),
        event("b", "task", timestamp("2026-11-02T05:00:00Z")),
        event("c", "task", timestamp("2026-11-09T05:00:00Z")),
        event("outside-end", "task", until),
    ], &[]).unwrap();
    let mut request = query(start, until, "America/New_York");
    request.granularity = TimelineGranularity::Week;
    let dashboard = query_dashboard(&store, &legacy_catalog(), &request).unwrap();
    assert_eq!(dashboard.timeline.iter().map(|bucket| bucket.timestamp_ms).collect::<Vec<_>>(), vec![
        timestamp("2026-10-26T04:00:00Z"), timestamp("2026-11-02T05:00:00Z"), timestamp("2026-11-09T05:00:00Z")]);
    assert!(dashboard.timeline.iter().all(|bucket| bucket.summary.event_count == 1));
}

#[test]
fn months_follow_calendar_across_year_leap_day_and_dst_with_empty_buckets() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let start = timestamp("2027-12-15T05:00:00Z");
    let until = timestamp("2028-04-01T04:00:00Z");
    store.commit_source(&cursor("first", 0), &[], &[
        event("leap", "task", timestamp("2028-02-29T17:00:00Z")),
        event("march", "task", timestamp("2028-03-01T05:00:00Z")),
        event("dst", "task", timestamp("2028-03-13T04:00:00Z")),
        event("outside", "task", until),
    ], &[]).unwrap();
    let mut request = query(start, until, "America/New_York");
    request.granularity = TimelineGranularity::Month;
    request.include_details = true;
    let dashboard = query_dashboard(&store, &legacy_catalog(), &request).unwrap();
    assert_eq!(dashboard.timeline.iter().map(|bucket| bucket.timestamp_ms).collect::<Vec<_>>(), vec![
        timestamp("2027-12-01T05:00:00Z"), timestamp("2028-01-01T05:00:00Z"),
        timestamp("2028-02-01T05:00:00Z"), timestamp("2028-03-01T05:00:00Z")]);
    assert_eq!(dashboard.timeline.iter().map(|bucket| bucket.summary.event_count).collect::<Vec<_>>(), vec![0, 0, 1, 2]);
    assert_eq!(dashboard.timeline.iter().map(|bucket| bucket.details.as_ref().unwrap().session_count)
        .collect::<Vec<_>>(), vec![0, 0, 1, 1]);
    assert!(dashboard.timeline[0].details.as_ref().unwrap().models.is_empty());
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
    let mut catalog = legacy_catalog();
    catalog
        .models
        .get_mut("gpt-6-astra")
        .unwrap()
        .tiers
        .first_mut()
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
fn proven_alias_merge_keeps_latest_usage_earliest_time_and_source_links() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let mut original = event("canonical", "task", 10);
    original.revision_ms = Some(100);
    let mut updated = event("provisional", "task-copy", 20);
    updated.revision_ms = Some(200);
    updated.tokens.output = Some(300);
    updated.tokens.total = Some(8300);
    let mut unrelated = updated.clone();
    unrelated.provider = Provider::Codex;
    store.commit_source(&cursor("first", 0), &[], &[original.clone()], &[]).unwrap();
    store.commit_source(&cursor("copy", 0), &[], &[updated, unrelated], &[]).unwrap();
    for _ in 0..2 {
        store.merge_event_ids(Provider::Claude, "canonical", &["provisional".into()]).unwrap();
    }
    let events = store.events().unwrap();
    assert_eq!(events.len(), 2);
    let merged = events.iter().find(|event| event.provider == Provider::Claude).unwrap();
    assert_eq!(merged.id, "canonical");
    assert_eq!(merged.timestamp_ms, 10);
    assert_eq!(merged.revision_ms, Some(200));
    assert_eq!(merged.tokens.output, Some(300));
    assert!(events.iter().any(|event| event.provider == Provider::Codex && event.id == "provisional"));
    let connection = Connection::open(scratch.db()).unwrap();
    let count: i64 = connection.query_row(
        "SELECT COUNT(*) FROM source_events WHERE provider='claude' AND event_id='canonical'",
        [], |row| row.get(0),
    ).unwrap();
    assert_eq!(count, 2);
    store.commit_source(&cursor("first", 0), &[], &[original], &[]).unwrap();
    assert_eq!(store.events().unwrap().into_iter().find(|e| e.provider == Provider::Claude).unwrap().tokens.output, Some(300));
}

#[test]
fn proven_alias_merge_can_create_the_canonical_identity() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    store.commit_source(&cursor("source", 0), &[], &[event("provisional", "task", 10)], &[]).unwrap();
    store.merge_event_ids(Provider::Claude, "canonical", &["provisional".into()]).unwrap();
    let events = store.events().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].id, "canonical");
    assert_eq!(events[0].tokens.total, Some(8100));
}

#[test]
fn legacy_codex_cache_write_uses_base_input_rate_without_an_additive_fee() {
    let catalog = legacy_catalog();
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
    let catalog = legacy_catalog();
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
    let catalog = legacy_catalog();
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
fn model_names_are_exact_and_harness_does_not_define_model_identity() {
    let catalog = legacy_catalog();
    let mut sample = event("a", "task", 1);
    sample.model = Some("claude-sonnet-4-6-unknown-suffix".into());
    let unknown = catalog.price(&sample);
    assert!(unknown.unpriced);
    assert_eq!(unknown.priced_tokens, 0);
    assert_eq!(unknown.input_units, 0);
    sample.model = Some("claude-sonnet-4-6".into());
    sample.provider = Provider::Codex;
    assert!(!catalog.price(&sample).unpriced);
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
    let catalog = legacy_catalog();
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
    let catalog = legacy_catalog();
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
    let dashboard = query_dashboard(&store, &legacy_catalog(), &query(0, 4000, "UTC")).unwrap();
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
        &legacy_catalog(),
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
        &legacy_catalog(),
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
        &legacy_catalog(),
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

#[test]
fn uncertain_dates_contribute_once_to_filtered_upper_totals_but_never_to_buckets() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let mut unknown = event("unknown-date", "task", 0);
    unknown.uncertain_time = Some(TimeBounds { since_ms: Some(1000), until_ms: Some(3000) });
    unknown.incomplete = true;
    store.commit_source(&cursor("first", 0), &[], &[unknown.clone()], &[]).unwrap();
    store.commit_source(&cursor("copy", 0), &[], &[unknown.clone()], &[]).unwrap();
    let mut request = query(1000, 2000, "UTC");
    request.include_details = true;
    let dashboard = query_dashboard(&store, &legacy_catalog(), &request).unwrap();
    assert_eq!(dashboard.summary.cost.total_tokens, 8100);
    assert_eq!(dashboard.summary.event_count, 1);
    assert_eq!(dashboard.summary.latest_event_ms, None);
    assert_eq!(dashboard.models[0].summary.cost.total_tokens, 8100);
    assert_eq!(dashboard.sessions[0].summary.cost.total_tokens, 8100);
    assert!(dashboard.timeline.iter().all(|bucket| bucket.summary.event_count == 0));
    assert!(dashboard.last_scan.unwrap().warnings[0].contains("included once"));
    assert_eq!(query_dashboard(&store, &legacy_catalog(), &query(3000,4000,"UTC")).unwrap().summary.event_count, 0);
    request.providers = Some(vec![Provider::Codex]);
    assert_eq!(query_dashboard(&store, &legacy_catalog(), &request).unwrap().summary.event_count, 0);
    unknown.timestamp_ms = 1500;
    unknown.uncertain_time = None;
    store.commit_source(&cursor("first",0), &[], &[unknown], &[]).unwrap();
    let dashboard = query_dashboard(&store, &legacy_catalog(), &query(1000,2000,"UTC")).unwrap();
    assert_eq!(dashboard.summary.event_count, 1);
    assert_eq!(dashboard.timeline.iter().map(|bucket| bucket.summary.event_count).sum::<usize>(),1);
}

#[test]
fn smaller_or_older_revisions_keep_the_higher_coherent_observation() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    let original = event("response", "task", 1000);
    store.commit_source(&cursor("first",0), &[], &[original.clone()], &[]).unwrap();
    let mut smaller = original.clone();
    smaller.timestamp_ms = 2000;
    smaller.tokens = Tokens { input_uncached: Some(100), output: Some(1), total: Some(101), ..Tokens::default() };
    store.commit_source(&cursor("first",0), &[], &[smaller], &[]).unwrap();
    let stored = store.events().unwrap().pop().unwrap();
    assert_eq!(stored.tokens, original.tokens);
    assert_eq!(stored.timestamp_ms,1000);
    assert!(stored.incomplete);
}

#[test]
fn analyzer_replay_replaces_old_ids_atomically_and_keeps_unavailable_sources() {
    let scratch = Scratch::new();
    let store = Store::open(&scratch.db()).unwrap();
    store.commit_source(&cursor("first",0), &[], &[event("old","task",1)], &[]).unwrap();
    store.commit_source(&cursor("unavailable-copy",0), &[], &[event("old","task",1)], &[]).unwrap();
    store.commit_source(&cursor("deleted-source",0), &[], &[event("retained","other",1)], &[]).unwrap();
    Connection::open(scratch.db()).unwrap().execute_batch("CREATE TRIGGER reject_replay BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'interrupted replay'); END;").unwrap();
    assert!(store.reparse_source(&cursor("first",0), &[], &[event("new","task",1)], &[]).is_err());
    assert!(store.events().unwrap().iter().any(|event| event.id=="old"));
    Connection::open(scratch.db()).unwrap().execute_batch("DROP TRIGGER reject_replay").unwrap();
    store.reparse_source(&cursor("first",0), &[], &[event("new","task",1)], &[]).unwrap();
    let ids=store.events().unwrap().into_iter().map(|event|event.id).collect::<Vec<_>>();
    assert_eq!(ids,vec!["new","retained"]);
}

#[test]
fn first_observation_bounds_unknown_dates_and_does_not_move_on_copied_replay() {
    let scratch=Scratch::new();
    let store=Store::open(&scratch.db()).unwrap();
    let mut unknown=event("unknown","task",0);
    unknown.uncertain_time=Some(TimeBounds::default());
    store.commit_source(&cursor("first",0),&[],&[unknown.clone()],&[]).unwrap();
    let bound=store.events().unwrap()[0].uncertain_time.as_ref().unwrap().until_ms.unwrap();
    store.commit_source(&cursor("copy",0),&[],&[unknown],&[]).unwrap();
    assert_eq!(store.events().unwrap()[0].uncertain_time.as_ref().unwrap().until_ms,Some(bound));
    assert_eq!(store.events_between(bound,bound+1000).unwrap().len(),0);
}
