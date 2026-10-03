use crate::{
    model::*,
    pricing::{cache_write_total, EventCost, PricingCatalog},
    store::Store,
};
use chrono::{DateTime, Duration, TimeZone, Timelike, Utc};
use chrono_tz::Tz;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Default)]
struct Aggregate {
    summary: UsageSummary,
    input_units: u128,
    read_units: u128,
    write_min_units: u128,
    write_max_units: u128,
    output_units: u128,
    tier_max_extra_units: u128,
    unknown: BTreeSet<String>,
    pricing_matches: BTreeSet<PricingMatch>,
}

impl Aggregate {
    fn add(&mut self, event: &UsageEvent, cost: &EventCost) {
        let summary = &mut self.summary;
        summary.input_tokens = summary
            .input_tokens
            .saturating_add(event.tokens.input_uncached.unwrap_or(0));
        summary.cache_read_tokens = summary
            .cache_read_tokens
            .saturating_add(event.tokens.cache_read.unwrap_or(0));
        summary.cache_write_tokens = summary
            .cache_write_tokens
            .saturating_add(cache_write_total(&event.tokens));
        summary.output_tokens = summary
            .output_tokens
            .saturating_add(event.tokens.output.unwrap_or(0));
        summary.reasoning_tokens = summary
            .reasoning_tokens
            .saturating_add(event.tokens.reasoning.unwrap_or(0));
        summary.event_count += 1;
        summary.incomplete_events += usize::from(event.incomplete);
        summary.latest_event_ms = Some(
            summary
                .latest_event_ms
                .map_or(event.timestamp_ms, |time| time.max(event.timestamp_ms)),
        );
        summary.cost.total_tokens = summary.cost.total_tokens.saturating_add(cost.total_tokens);
        summary.cost.priced_tokens = summary
            .cost
            .priced_tokens
            .saturating_add(cost.priced_tokens);
        summary.cost.unpriced_events += usize::from(cost.unpriced);
        summary.cost.uncertain_events += usize::from(cost.uncertain);
        self.input_units += cost.input_units;
        self.read_units += cost.read_units;
        self.write_min_units += cost.write_min_units;
        self.write_max_units += cost.write_max_units;
        self.output_units += cost.output_units;
        self.tier_max_extra_units += cost.tier_max_extra_units;
        if let Some(model) = &cost.unknown_model {
            self.unknown.insert(model.clone());
        }
        if let Some(matched) = &cost.pricing_match {
            self.pricing_matches.insert(matched.clone());
        }
    }

    fn finish(mut self) -> UsageSummary {
        let cost = &mut self.summary.cost;
        cost.input_usd = usd(self.input_units);
        cost.cache_read_usd = usd(self.read_units);
        cost.cache_write_min_usd = usd(self.write_min_units);
        cost.cache_write_max_usd = usd(self.write_max_units);
        cost.output_usd = usd(self.output_units);
        cost.min_usd =
            usd(self.input_units + self.read_units + self.write_min_units + self.output_units);
        cost.max_usd = usd(self.input_units
            + self.read_units
            + self.write_max_units
            + self.output_units
            + self.tier_max_extra_units);
        cost.unknown_models = self.unknown.into_iter().collect();
        cost.pricing_matches = self.pricing_matches.into_iter().collect();
        self.summary
    }
}

fn usd(units: u128) -> f64 {
    units as f64 / 1_000_000_000_000_000.0
}
fn anonymous(kind: &str, value: &str) -> String {
    let digest = Sha256::digest(value.as_bytes());
    format!("{kind}:{:x}", digest)[..kind.len() + 13].to_owned()
}
fn session_key(provider: Provider, id: &str) -> String {
    format!("{}:{id}", provider.as_str())
}

/// Sessions contain their own usage; summing rows never counts descendants twice.
/// Time bounds are [since, until), with local calendar buckets including DST.
pub fn query_dashboard(
    store: &Store,
    catalog: &PricingCatalog,
    query: &Query,
) -> CoreResult<Dashboard> {
    if query.since_ms >= query.until_ms {
        return Err("Query end must be after start".into());
    }
    let timezone: Tz = query
        .timezone
        .parse()
        .map_err(|_| format!("Unknown timezone: {}", query.timezone))?;
    let hourly = i128::from(query.until_ms) - i128::from(query.since_ms) <= 3 * 86_400_000;
    let mut timeline = empty_timeline(query, timezone, hourly)?;
    let metadata: BTreeMap<_, _> = store
        .sessions()?
        .into_iter()
        .map(|session| (session_key(session.provider, &session.id), session))
        .collect();
    let mut summary = Aggregate::default();
    let mut providers: BTreeMap<Provider, Aggregate> = BTreeMap::new();
    let mut models: BTreeMap<String, Aggregate> = BTreeMap::new();
    let mut projects: BTreeMap<String, Aggregate> = BTreeMap::new();
    let mut sessions: BTreeMap<String, Aggregate> = BTreeMap::new();
    let mut project_labels = BTreeMap::new();
    let mut session_labels = BTreeMap::new();
    let mut session_providers = BTreeMap::new();
    for event in store.events_between(query.since_ms, query.until_ms)? {
        let cost = catalog.price(&event);
        summary.add(&event, &cost);
        providers
            .entry(event.provider)
            .or_default()
            .add(&event, &cost);
        models
            .entry(event.model.clone().unwrap_or_else(|| "unknown".into()))
            .or_default()
            .add(&event, &cost);
        let key = session_key(event.provider, &event.session_id);
        let session = metadata.get(&key);
        let path = session.and_then(|session| session.project_path.as_deref());
        let project_id = path.map_or_else(|| "unknown".into(), |path| anonymous("project", path));
        let label = if query.show_paths {
            path.unwrap_or("unknown").to_owned()
        } else {
            project_id.clone()
        };
        project_labels.insert(project_id.clone(), label);
        projects.entry(project_id).or_default().add(&event, &cost);
        session_labels.insert(key.clone(), anonymous("session", &key));
        session_providers.insert(key.clone(), event.provider);
        sessions.entry(key).or_default().add(&event, &cost);
        let timestamp = bucket_start(event.timestamp_ms, timezone, hourly)?;
        timeline.entry(timestamp).or_default().add(&event, &cost);
    }
    let provider_rows = providers
        .into_iter()
        .map(|(provider, value)| BreakdownRow {
            label: provider.label().into(),
            provider: Some(provider),
            id: provider.as_str().into(),
            parent_id: None,
            summary: value.finish(),
        })
        .collect();
    let model_rows = rows(models, |id| (id.to_owned(), None, None));
    let project_rows = rows(projects, |id| (project_labels[id].clone(), None, None));
    let mut session_rows = rows(sessions, |id| {
        let session = metadata.get(id);
        let provider = session.map(|session| session.provider).or_else(|| session_providers.get(id).copied());
        let parent = session.and_then(|session| {
            session
                .parent_id
                .as_ref()
                .map(|parent| session_key(session.provider, parent))
        });
        (session_labels[id].clone(), provider, parent)
    });
    // Include structural ancestors with zero own usage so tasks remain navigable
    // when the requested window only contains a subagent.
    let mut included: BTreeSet<_> = session_rows.iter().map(|row| row.id.clone()).collect();
    let mut pending: Vec<_> = session_rows
        .iter()
        .filter_map(|row| row.parent_id.clone())
        .collect();
    while let Some(id) = pending.pop() {
        if !included.insert(id.clone()) {
            continue;
        }
        if let Some(session) = metadata.get(&id) {
            let parent = session
                .parent_id
                .as_ref()
                .map(|parent| session_key(session.provider, parent));
            if let Some(parent) = &parent {
                pending.push(parent.clone());
            }
            session_rows.push(BreakdownRow {
                label: anonymous("session", &id),
                id,
                provider: Some(session.provider),
                parent_id: parent,
                summary: UsageSummary::default(),
            });
        }
    }
    session_rows.sort_by(|a, b| {
        b.summary
            .latest_event_ms
            .cmp(&a.summary.latest_event_ms)
            .then_with(|| a.id.cmp(&b.id))
    });
    Ok(Dashboard {
        schema_version: 1,
        summary: summary.finish(),
        providers: provider_rows,
        models: model_rows,
        projects: project_rows,
        sessions: session_rows,
        timeline: timeline
            .into_iter()
            .map(|(timestamp_ms, value)| TimelineBucket {
                timestamp_ms,
                summary: value.finish(),
            })
            .collect(),
        states: store.states()?,
        catalog_id: catalog.id.clone(),
        catalog_retrieved_at: catalog.retrieved_at.clone(),
        catalog_sources: catalog.sources.clone(),
        last_scan: store.last_scan()?,
    })
}

fn rows(
    values: BTreeMap<String, Aggregate>,
    label: impl Fn(&str) -> (String, Option<Provider>, Option<String>),
) -> Vec<BreakdownRow> {
    let mut result: Vec<_> = values
        .into_iter()
        .map(|(id, value)| {
            let (label, provider, parent_id) = label(&id);
            BreakdownRow {
                id,
                label,
                provider,
                parent_id,
                summary: value.finish(),
            }
        })
        .collect();
    result.sort_by(|a, b| {
        b.summary
            .cost
            .max_usd
            .total_cmp(&a.summary.cost.max_usd)
            .then_with(|| a.id.cmp(&b.id))
    });
    result
}

fn bucket_start(timestamp_ms: i64, timezone: Tz, hourly: bool) -> CoreResult<i64> {
    let time = DateTime::<Utc>::from_timestamp_millis(timestamp_ms)
        .ok_or("Timestamp outside calendar range")?
        .with_timezone(&timezone);
    if hourly {
        // Subtract elapsed sub-hour time, preserving the offset during repeated
        // autumn hours rather than merging two distinct hours.
        Ok(timestamp_ms
            - i64::from(time.minute()) * 60_000
            - i64::from(time.second()) * 1000
            - i64::from(time.timestamp_subsec_millis()))
    } else {
        let midnight = time
            .date_naive()
            .and_hms_opt(0, 0, 0)
            .ok_or("Invalid calendar date")?;
        // Some historical zones move clocks at midnight. First valid local minute
        // is the beginning of that calendar day.
        for minutes in 0..=180 {
            if let Some(start) = timezone
                .from_local_datetime(&(midnight + Duration::minutes(minutes)))
                .earliest()
            {
                return Ok(start.timestamp_millis());
            }
        }
        Err("Calendar day has no valid start in selected timezone".into())
    }
}

fn empty_timeline(
    query: &Query,
    timezone: Tz,
    hourly: bool,
) -> CoreResult<BTreeMap<i64, Aggregate>> {
    let mut result = BTreeMap::new();
    let mut cursor = bucket_start(query.since_ms, timezone, hourly)?;
    while cursor < query.until_ms {
        if result.len() >= 100_000 {
            return Err("Query exceeds 100,000 calendar buckets".into());
        }
        result.insert(cursor, Aggregate::default());
        cursor = if hourly {
            cursor.checked_add(3_600_000).ok_or("Timestamp overflow")?
        } else {
            let time = DateTime::<Utc>::from_timestamp_millis(cursor)
                .ok_or("Timestamp outside calendar range")?
                .with_timezone(&timezone);
            let next = time
                .date_naive()
                .succ_opt()
                .ok_or("Timestamp outside calendar range")?
                .and_hms_opt(12, 0, 0)
                .ok_or("Invalid calendar date")?;
            let noon = timezone
                .from_local_datetime(&next)
                .earliest()
                .ok_or("Calendar date unavailable in selected timezone")?;
            bucket_start(noon.timestamp_millis(), timezone, false)?
        };
    }
    Ok(result)
}
