use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::PathBuf;

pub type CoreResult<T> = Result<T, String>;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Provider {
    Codex,
    Claude,
    OpenCode,
    Antigravity,
}

impl Provider {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Codex => "codex",
            Self::Claude => "claude",
            Self::OpenCode => "opencode",
            Self::Antigravity => "antigravity",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Codex => "Codex",
            Self::Claude => "Claude Code",
            Self::OpenCode => "OpenCode",
            Self::Antigravity => "Antigravity",
        }
    }
}

/// Mutually exclusive input categories. Reasoning is a subset of output.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Tokens {
    pub input_uncached: Option<u64>,
    pub cache_read: Option<u64>,
    pub cache_write: Option<u64>,
    pub cache_write_5m: Option<u64>,
    pub cache_write_1h: Option<u64>,
    pub output: Option<u64>,
    pub reasoning: Option<u64>,
    pub total: Option<u64>,
}

impl Tokens {
    pub fn known_total(&self) -> u64 {
        self.input_uncached.unwrap_or(0)
            .saturating_add(self.cache_read.unwrap_or(0))
            .saturating_add(self.cache_write.unwrap_or_else(|| {
                self.cache_write_5m.unwrap_or(0).saturating_add(self.cache_write_1h.unwrap_or(0))
            }))
            .saturating_add(self.output.unwrap_or(0))
    }

    /// Compare complete observations, never splice conflicting category maxima.
    pub fn upper_key(&self) -> (u64, usize) {
        (self.total.unwrap_or(0).max(self.known_total()),
         [self.input_uncached, self.cache_read, self.cache_write, self.output,
          self.reasoning, self.cache_write_5m, self.cache_write_1h]
            .iter().filter(|value| value.is_some()).count())
    }
}

/// Possible occurrence interval [since_ms, until_ms); absent bounds are unknown.
/// This is ledger metadata, not a fabricated occurrence date.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct TimeBounds {
    pub since_ms: Option<i64>,
    pub until_ms: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UsageEvent {
    pub id: String,
    pub provider: Provider,
    pub session_id: String,
    pub timestamp_ms: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub uncertain_time: Option<TimeBounds>,
    pub model: Option<String>,
    #[serde(default)]
    pub revision_ms: Option<i64>,
    /// Model service identity; `provider` above is the collection harness.
    #[serde(default)]
    pub model_provider: Option<String>,
    pub attribution: String,
    pub tokens: Tokens,
    #[serde(default)]
    pub incomplete: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionMetadata {
    pub id: String,
    pub provider: Provider,
    pub parent_id: Option<String>,
    pub project_path: Option<String>,
    pub title: Option<String>,
}

/// Only allowlisted usage/context/quota metadata is stored here, never bodies.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ObservedState {
    pub provider: Provider,
    pub session_id: String,
    pub timestamp_ms: i64,
    pub kind: String,
    pub data: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceCursor {
    pub identity: String,
    pub path: String,
    pub offset: u64,
    pub length: u64,
    pub modified_ns: String,
    pub head_hash: String,
    pub parser_state: Value,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ScanReport {
    pub files_discovered: usize,
    pub files_changed: usize,
    pub events_upserted: usize,
    pub checked_at_ms: i64,
    pub warnings: Vec<String>,
    #[serde(default)]
    pub undated_events: usize,
    #[serde(default)]
    pub undated_tokens: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CoreConfig {
    pub home: PathBuf,
    pub database_path: PathBuf,
    pub codex_root: Option<PathBuf>,
    #[serde(default)]
    pub claude_roots: Vec<PathBuf>,
    #[serde(default)]
    pub opencode_root: Option<PathBuf>,
    #[serde(default)]
    pub antigravity_roots: Vec<PathBuf>,
    pub pricing_path: Option<PathBuf>,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TimelineGranularity {
    #[default]
    Auto,
    Hour,
    Day,
    Week,
    Month,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Query {
    pub since_ms: i64,
    pub until_ms: i64,
    pub timezone: String,
    #[serde(default)]
    pub show_paths: bool,
    /// None selects all harnesses; an empty list selects none.
    #[serde(default)]
    pub providers: Option<Vec<Provider>>,
    #[serde(default)]
    pub granularity: TimelineGranularity,
    /// Opt in to bucket model breakdowns, distinct session counts and session models.
    #[serde(default)]
    pub include_details: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct PricingMatch {
    pub model: String,
    pub priced_model: String,
    pub source: String,
    pub kind: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct CostSummary {
    pub min_usd: f64,
    pub max_usd: f64,
    pub input_usd: f64,
    pub cache_read_usd: f64,
    pub cache_write_min_usd: f64,
    pub cache_write_max_usd: f64,
    pub output_usd: f64,
    pub priced_tokens: u64,
    pub total_tokens: u64,
    pub unpriced_events: usize,
    pub uncertain_events: usize,
    pub unknown_models: Vec<String>,
    #[serde(default)]
    pub pricing_matches: Vec<PricingMatch>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct UsageSummary {
    pub cost: CostSummary,
    pub input_tokens: u64,
    pub cache_read_tokens: u64,
    pub cache_write_tokens: u64,
    pub output_tokens: u64,
    pub reasoning_tokens: u64,
    pub event_count: usize,
    pub incomplete_events: usize,
    pub latest_event_ms: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BreakdownRow {
    pub id: String,
    pub label: String,
    pub provider: Option<Provider>,
    pub parent_id: Option<String>,
    pub summary: UsageSummary,
    /// Session model with the most tokens in this query window; ties use model name.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub primary_model: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimelineDetails {
    /// Distinct (harness, session) pairs with events in this bucket, not daily counts summed.
    pub session_count: usize,
    pub models: Vec<BreakdownRow>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimelineBucket {
    pub timestamp_ms: i64,
    pub summary: UsageSummary,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub details: Option<TimelineDetails>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Dashboard {
    pub schema_version: u32,
    pub summary: UsageSummary,
    pub providers: Vec<BreakdownRow>,
    pub models: Vec<BreakdownRow>,
    pub projects: Vec<BreakdownRow>,
    pub sessions: Vec<BreakdownRow>,
    pub timeline: Vec<TimelineBucket>,
    pub states: Vec<ObservedState>,
    pub catalog_id: String,
    pub catalog_retrieved_at: String,
    pub catalog_sources: Vec<String>,
    pub last_scan: Option<ScanReport>,
}
