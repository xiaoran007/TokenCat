use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::PathBuf;

pub type CoreResult<T> = Result<T, String>;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Provider {
    Codex,
    Claude,
}

impl Provider {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Codex => "codex",
            Self::Claude => "claude",
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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UsageEvent {
    pub id: String,
    pub provider: Provider,
    pub session_id: String,
    pub timestamp_ms: i64,
    pub model: Option<String>,
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
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CoreConfig {
    pub home: PathBuf,
    pub database_path: PathBuf,
    pub codex_root: Option<PathBuf>,
    #[serde(default)]
    pub claude_roots: Vec<PathBuf>,
    pub pricing_path: Option<PathBuf>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Query {
    pub since_ms: i64,
    pub until_ms: i64,
    pub timezone: String,
    #[serde(default)]
    pub show_paths: bool,
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
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimelineBucket {
    pub timestamp_ms: i64,
    pub summary: UsageSummary,
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
