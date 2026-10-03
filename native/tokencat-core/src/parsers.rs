//! Metadata-only adapters. Serde skips unknown fields, including message bodies.
use crate::model::*;
use chrono::DateTime;
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::path::Path;

pub(crate) const ANALYSIS_VERSION: u64 = 2;

#[derive(Clone, Default, Serialize, Deserialize)]
pub(crate) struct ParserState {
    #[serde(default)]
    pub analysis_version: u64,
    pub generation: u64,
    pub context: Context,
}

#[derive(Clone, Default, Serialize, Deserialize)]
pub(crate) struct Context {
    session: Option<String>,
    parent: Option<String>,
    project: Option<String>,
    configured_model: Option<String>,
    reported_model: Option<String>,
    model_provider: Option<String>,
    previous: Option<RawTokens>,
    previous_last: Option<RawTokens>,
    epoch: u64,
    modern: bool,
    fork: bool,
    started_ms: Option<i64>,
    agent: Option<String>,
    sidechain: bool,
    #[serde(default)]
    usage_sequence: u64,
}

#[derive(Default)]
pub(crate) struct Batch {
    pub sessions: Vec<SessionMetadata>,
    pub events: Vec<UsageEvent>,
    pub states: Vec<ObservedState>,
    pub warnings: Vec<String>,
}

#[derive(Clone, Default, Deserialize, Serialize, PartialEq, Eq)]
struct RawTokens {
    input_tokens: Option<u64>,
    #[serde(alias = "cache_read_input_tokens")]
    cached_input_tokens: Option<u64>,
    #[serde(default = "zero_tokens")]
    cache_write_input_tokens: Option<u64>,
    output_tokens: Option<u64>,
    reasoning_output_tokens: Option<u64>,
    total_tokens: Option<u64>,
}
fn zero_tokens() -> Option<u64> {
    Some(0)
}
impl RawTokens {
    fn upper_candidate(&self, last: Option<&Self>) -> CoreResult<Self> {
        let delta = self.tokens();
        let Some(last) = last else { return delta.map(|_| self.clone()) };
        match (delta, last.tokens()) {
            (Ok(delta), Ok(response)) => Ok(if response.upper_key() > delta.upper_key() {
                last.clone()
            } else { self.clone() }),
            (Ok(_), Err(_)) => Ok(self.clone()),
            (Err(_), Ok(_)) => Ok(last.clone()),
            (Err(error), Err(_)) => Err(error),
        }
    }
    fn difference(&self, prior: &Self) -> Self {
        fn sub(a: Option<u64>, b: Option<u64>) -> Option<u64> {
            // A category can only be differenced across two known readings.
            // Recovery after a missing reading establishes a baseline for the
            // next interval, rather than charging the entire cumulative value.
            a.zip(b)
                .and_then(|(current, previous)| current.checked_sub(previous))
        }
        Self {
            input_tokens: sub(self.input_tokens, prior.input_tokens),
            cached_input_tokens: sub(self.cached_input_tokens, prior.cached_input_tokens),
            cache_write_input_tokens: sub(
                self.cache_write_input_tokens,
                prior.cache_write_input_tokens,
            ),
            output_tokens: sub(self.output_tokens, prior.output_tokens),
            reasoning_output_tokens: sub(
                self.reasoning_output_tokens,
                prior.reasoning_output_tokens,
            ),
            total_tokens: sub(self.total_tokens, prior.total_tokens),
        }
    }
    fn reset_from(&self, prior: &Self) -> bool {
        [
            (self.input_tokens, prior.input_tokens),
            (self.cached_input_tokens, prior.cached_input_tokens),
            (
                self.cache_write_input_tokens,
                prior.cache_write_input_tokens,
            ),
            (self.output_tokens, prior.output_tokens),
            (self.reasoning_output_tokens, prior.reasoning_output_tokens),
            (self.total_tokens, prior.total_tokens),
        ]
        .iter()
        .any(|(a, b)| matches!((a,b), (Some(a),Some(b)) if a<b))
    }
    fn tokens(&self) -> CoreResult<Tokens> {
        let cache = self.cached_input_tokens;
        let write = self.cache_write_input_tokens;
        if let (Some(input), Some(cache)) = (self.input_tokens, cache) {
            if cache > input {
                return Err("cached input exceeds input".into());
            }
        }
        if let (Some(output), Some(reasoning)) = (self.output_tokens, self.reasoning_output_tokens)
        {
            if reasoning > output {
                return Err("reasoning exceeds output".into());
            }
        }
        // Codex cache writes are separately reported; input includes read/write categories.
        let cached_total = cache
            .unwrap_or(0)
            .checked_add(write.unwrap_or(0))
            .ok_or("token count overflow")?;
        let uncached = self
            .input_tokens
            .zip(cache)
            .zip(write)
            .map(|((input, _), _)| input)
            .map(|n| {
                n.checked_sub(cached_total)
                    .ok_or_else(|| "cached input exceeds input".to_string())
            })
            .transpose()?;
        let calculated_total = self
            .input_tokens
            .zip(self.output_tokens)
            .map(|(a, b)| {
                a.checked_add(b)
                    .ok_or_else(|| "token count overflow".to_string())
            })
            .transpose()?;
        Ok(Tokens {
            input_uncached: uncached,
            cache_read: cache,
            cache_write: self.cache_write_input_tokens,
            output: self.output_tokens,
            reasoning: self.reasoning_output_tokens,
            total: self.total_tokens.or(calculated_total),
            ..Default::default()
        })
    }
    fn nonzero(&self) -> bool {
        [
            self.input_tokens,
            self.cached_input_tokens,
            self.cache_write_input_tokens,
            self.output_tokens,
            self.total_tokens,
        ]
        .iter()
        .any(|v| v.unwrap_or(0) > 0)
    }
}

#[derive(Deserialize)]
struct CodexLine {
    #[serde(rename = "type")]
    kind: String,
    timestamp: Option<String>,
    payload: Option<CodexPayload>,
}
#[derive(Default, Deserialize)]
struct CodexPayload {
    #[serde(rename = "type")]
    kind: Option<String>,
    id: Option<String>,
    thread_id: Option<String>,
    session_id: Option<String>,
    response_id: Option<String>,
    cwd: Option<String>,
    model: Option<String>,
    model_name: Option<String>,
    model_provider: Option<String>,
    to_model: Option<String>,
    parent_thread_id: Option<String>,
    forked_from_id: Option<String>,
    timestamp: Option<String>,
    source: Option<SessionSource>,
    info: Option<UsageInfo>,
    usage: Option<RawTokens>,
    rate_limits: Option<RateLimits>,
}
#[derive(Deserialize)]
#[serde(untagged)]
enum SessionSource {
    Named(String),
    SubAgent { subagent: SubAgentSource },
}
#[derive(Deserialize)]
struct SubAgentSource {
    thread_spawn: Option<ThreadSpawn>,
}
#[derive(Deserialize)]
struct ThreadSpawn {
    parent_thread_id: Option<String>,
}
#[derive(Deserialize)]
struct UsageInfo {
    total_token_usage: Option<RawTokens>,
    last_token_usage: Option<RawTokens>,
    model_context_window: Option<u64>,
    model: Option<String>,
    model_name: Option<String>,
}
#[derive(Deserialize, Serialize)]
struct RateLimits {
    primary: Option<RateWindow>,
    secondary: Option<RateWindow>,
    limit_id: Option<String>,
}
#[derive(Deserialize, Serialize)]
struct RateWindow {
    used_percent: Option<f64>,
    window_minutes: Option<u64>,
    resets_at: Option<i64>,
}

pub(crate) fn parse_line(
    provider: Provider,
    path: &Path,
    line: &[u8],
    state: &mut ParserState,
    batch: &mut Batch,
) -> CoreResult<()> {
    match provider {
        Provider::Codex => parse_codex(line, state, batch),
        Provider::Claude => parse_claude(path, line, state, batch),
        Provider::OpenCode | Provider::Antigravity => {
            Err("This harness uses SQLite metadata, not JSONL".into())
        }
    }
}
fn timestamp(raw: Option<&str>) -> CoreResult<i64> {
    raw.and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .map(|d| d.timestamp_millis())
        .ok_or_else(|| "missing or invalid usage timestamp".into())
}
fn digest(value: &impl Serialize) -> String {
    format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(value).expect("metadata serialization"))
    )
}
fn metadata(c: &Context, provider: Provider, id: String) -> SessionMetadata {
    SessionMetadata {
        id,
        provider,
        parent_id: c.parent.clone(),
        project_path: c.project.clone(),
        title: None,
    }
}
fn parse_codex(line: &[u8], state: &mut ParserState, batch: &mut Batch) -> CoreResult<()> {
    let row: CodexLine =
        serde_json::from_slice(line).map_err(|_| "invalid Codex metadata record".to_string())?;
    let Some(p) = row.payload else { return Ok(()) };
    let c = &mut state.context;
    if row.kind == "session_meta" {
        c.session = p.thread_id.or(p.id).or(p.session_id);
        c.model_provider = p
            .model_provider
            .filter(|provider| !provider.trim().is_empty());
        c.parent = p.parent_thread_id.or_else(|| match p.source {
            Some(SessionSource::SubAgent { subagent }) => {
                subagent.thread_spawn.and_then(|s| s.parent_thread_id)
            }
            Some(SessionSource::Named(name)) => {
                let _ = name;
                None
            }
            None => None,
        });
        c.fork = p.forked_from_id.is_some();
        c.started_ms = timestamp(p.timestamp.as_deref().or(row.timestamp.as_deref())).ok();
        c.project = p.cwd;
        if let Some(id) = c.session.clone() {
            batch.sessions.push(metadata(c, Provider::Codex, id));
        }
        return Ok(());
    }
    if row.kind == "turn_context" {
        c.configured_model = p.model.or(p.model_name);
        c.reported_model = None;
        if p.cwd.is_some() {
            c.project = p.cwd;
        }
        if let Some(id) = c.session.clone() {
            batch.sessions.push(metadata(c, Provider::Codex, id));
        }
        return Ok(());
    }
    if row.kind == "event_msg" && p.kind.as_deref() == Some("model_reroute") {
        c.reported_model = p.to_model;
        return Ok(());
    }
    if row.kind == "token_usage_record" {
        let Some(raw) = p.usage else {
            return Err("usage record has no usage".into());
        };
        let id = p
            .response_id
            .ok_or("usage record has no response identifier")?;
        let session = p
            .thread_id
            .or_else(|| c.session.clone())
            .ok_or("usage record has no thread identifier")?;
        let time = timestamp(row.timestamp.as_deref()).ok();
        let tokens = raw.tokens()?;
        c.modern = true;
        if !raw.nonzero() {
            return Ok(());
        }
        let explicit = p.model.or(p.model_name);
        let model = explicit
            .clone()
            .or(c.reported_model.clone())
            .or(c.configured_model.clone());
        let attribution = if explicit.is_some() || c.reported_model.is_some() {
            "reported"
        } else if model.is_some() {
            "configured"
        } else {
            "unknown"
        };
        batch.events.push(UsageEvent {
            uncertain_time: time.is_none().then_some(TimeBounds::default()),
            id: format!("response:{id}"),
            provider: Provider::Codex,
            session_id: session,
            timestamp_ms: time.unwrap_or(0),
            model,
            model_provider: c.model_provider.clone().or_else(|| Some("openai".into())),
            revision_ms: None,
            attribution: attribution.into(),
            incomplete: time.is_none() || tokens.input_uncached.is_none() || tokens.output.is_none(),
            tokens,
        });
        return Ok(());
    }
    if row.kind != "event_msg" || p.kind.as_deref() != Some("token_count") {
        return Ok(());
    }
    let session = c
        .session
        .clone()
        .ok_or("usage record has no session metadata")?;
    let time = timestamp(row.timestamp.as_deref()).ok();
    if let (Some(limits), Some(time)) = (p.rate_limits, time) {
        batch.states.push(ObservedState {
            provider: Provider::Codex,
            session_id: session.clone(),
            timestamp_ms: time,
            kind: "quota".into(),
            data: serde_json::to_value(limits).map_err(|e| e.to_string())?,
        });
    }
    let Some(info) = p.info else { return Ok(()) };
    if let (Some(window), Some(time)) = (info.model_context_window, time) {
        batch.states.push(ObservedState {provider:Provider::Codex,session_id:session.clone(),timestamp_ms:time,kind:"context".into(),data:json!({"context_window":window,"last_input_tokens":info.last_token_usage.as_ref().and_then(|r|r.input_tokens),"last_output_tokens":info.last_token_usage.as_ref().and_then(|r|r.output_tokens)})});
    }
    // Modern response records are authoritative; token_count is a mutable context snapshot.
    if c.modern {
        return Ok(());
    }
    let total = info.total_token_usage;
    let last = info.last_token_usage;
    let mut incomplete_baseline = false;
    let raw = if let Some(ref total) = total {
        match &c.previous {
            Some(prior) if total == prior => None,
            Some(prior) if total.reset_from(prior) => {
                c.epoch += 1;
                incomplete_baseline = true;
                batch
                    .warnings
                    .push("Codex cumulative usage baseline reset; prior ledger retained".into());
                last.clone()
            }
            Some(prior) => {
                let delta = total.difference(prior);
                let selected = delta.upper_candidate(last.as_ref())?;
                incomplete_baseline = last.as_ref().is_some_and(|last| &delta != last);
                Some(selected)
            }
            None => {
                if c.previous_last.is_some() && last.as_ref() == c.previous_last.as_ref() {
                    // Quota/context snapshots can carry the last response while
                    // restoring a cumulative baseline. It is already recorded.
                    batch.warnings.push("Codex cumulative baseline recovered with unchanged last usage; ambiguous response count was not guessed".into());
                    None
                } else if c.previous_last.is_some() && last.is_none() {
                    // A last-only response broke the cumulative baseline. Its
                    // later cumulative total includes already recorded usage.
                    // Reestablish the baseline without charging that history.
                    incomplete_baseline = true;
                    batch.warnings.push("Codex cumulative baseline recovered without a last response; historical usage was not charged again".into());
                    None
                } else {
                    let baseline_tokens = total.tokens()?;
                    let history = last.as_ref().map(|last| last.tokens())
                        .transpose()?.map_or(0, |last| baseline_tokens.upper_key().0.saturating_sub(last.upper_key().0));
                    incomplete_baseline = history > 0;
                    if incomplete_baseline && !c.fork && c.usage_sequence == 0 {
                        let residual = total.difference(last.as_ref().unwrap());
                        // Historical category differences can be contradictory
                        // even when the total is known. Keep the total without
                        // fabricating a split or rejecting the current response.
                        let tokens = match residual.tokens() {
                            Ok(mut tokens) if tokens.known_total() <= history => {
                                tokens.total = Some(history); tokens
                            }
                            _ => Tokens { total: Some(history), ..Default::default() },
                        };
                        if history > 0 {
                            batch.events.push(UsageEvent {
                                id: format!("baseline:{}", digest(&(session.clone(), c.epoch))),
                                provider: Provider::Codex, session_id: session.clone(),
                                timestamp_ms: 0,
                                uncertain_time: Some(TimeBounds { since_ms: None, until_ms: time.map(|time| time.saturating_add(1)) }),
                                model: None, model_provider: c.model_provider.clone(),
                                revision_ms: time, attribution: "historical model unknown".into(),
                                tokens, incomplete: true,
                            });
                            batch.warnings.push("Initial Codex cumulative history retained as uncertain-date usage in upper estimates".into());
                        }
                    }
                    Some(if history > 0 { last.clone().unwrap() } else {
                        total.upper_candidate(last.as_ref())?
                    })
                }
            }
        }
    } else {
        incomplete_baseline = true;
        // Equal token values alone cannot establish that two requests are the
        // same. Stable IDs/timestamps reconcile actual copies in the ledger.
        last.clone()
    };
    if total.is_some() || last.is_some() {
        c.previous = total;
    }
    if last.is_some() {
        c.previous_last = last;
    }
    let Some(raw) = raw else { return Ok(()) };
    if !raw.nonzero() {
        return Ok(());
    }
    // A fork copies its parent's earlier rollout events. Those are not new usage.
    if c.fork && c.started_ms.is_some_and(|start| time.is_some_and(|time| time < start)) {
        return Ok(());
    }
    let explicit = p.model.or(p.model_name).or(info.model).or(info.model_name);
    let model = explicit
        .clone()
        .or(c.reported_model.clone())
        .or(c.configured_model.clone());
    let attribution = if explicit.is_some() || c.reported_model.is_some() {
        "reported"
    } else if model.is_some() {
        "configured"
    } else {
        "unknown"
    };
    let tokens = raw.tokens()?;
    c.usage_sequence += 1;
    let event_id = digest(&(session.clone(), time, c.epoch, model.clone(), &raw,
        time.is_none().then_some(c.usage_sequence)));
    batch.events.push(UsageEvent {
        uncertain_time: time.is_none().then_some(TimeBounds::default()),
        id: p.response_id.map(|id| format!("response:{id}")).unwrap_or_else(|| format!("legacy:{event_id}")),
        provider: Provider::Codex,
        session_id: session,
        timestamp_ms: time.unwrap_or(0),
        model,
        model_provider: c.model_provider.clone().or_else(|| Some("openai".into())),
        revision_ms: None,
        attribution: attribution.into(),
        incomplete: time.is_none() || incomplete_baseline
            || tokens.input_uncached.is_none()
            || tokens.output.is_none(),
        tokens,
    });
    Ok(())
}

#[derive(Deserialize)]
struct ClaudeLine {
    #[serde(rename = "type")]
    kind: String,
    #[serde(rename = "sessionId")]
    session_id: Option<String>,
    #[serde(rename = "requestId")]
    request_id: Option<String>,
    uuid: Option<String>,
    #[serde(rename = "agentId")]
    agent_id: Option<String>,
    #[serde(rename = "isSidechain", default)]
    sidechain: bool,
    #[serde(rename = "isApiErrorMessage", default)]
    api_error: bool,
    cwd: Option<String>,
    timestamp: Option<String>,
    message: Option<ClaudeMessage>,
}
#[derive(Deserialize)]
struct ClaudeMessage {
    id: Option<String>,
    role: Option<String>,
    model: Option<String>,
    usage: Option<ClaudeUsage>,
}
#[derive(Deserialize)]
struct ClaudeUsage {
    input_tokens: Option<u64>,
    cache_read_input_tokens: Option<u64>,
    cache_creation_input_tokens: Option<u64>,
    output_tokens: Option<u64>,
    cache_creation: Option<CacheCreation>,
}
#[derive(Deserialize)]
struct CacheCreation {
    ephemeral_5m_input_tokens: Option<u64>,
    ephemeral_1h_input_tokens: Option<u64>,
}
fn parse_claude(
    path: &Path,
    line: &[u8],
    state: &mut ParserState,
    batch: &mut Batch,
) -> CoreResult<()> {
    let row: ClaudeLine =
        serde_json::from_slice(line).map_err(|_| "invalid Claude metadata record".to_string())?;
    let c = &mut state.context;
    let components: Vec<_> = path.components().collect();
    let project_index = components.iter().rposition(|v| v.as_os_str() == "projects");
    let subagents: Vec<usize> = components
        .iter()
        .enumerate()
        .filter(|(i, v)| {
            v.as_os_str() == "subagents" && project_index.is_none_or(|project| *i > project + 1)
        })
        .map(|(i, _)| i)
        .collect();
    let main_from_path = subagents
        .first()
        .and_then(|i| i.checked_sub(1))
        .and_then(|i| components[i].as_os_str().to_str())
        .map(str::to_owned);
    if row.session_id.is_some() {
        c.session = row.session_id;
    }
    if row.cwd.is_some() {
        c.project = row.cwd;
    }
    if row.agent_id.is_some() {
        c.agent = row.agent_id;
    }
    c.sidechain |= row.sidechain || !subagents.is_empty();
    // Non-assistant bookkeeping rows may precede the first session-bearing row.
    if c.session.is_none() && main_from_path.is_none() && row.kind != "assistant" {
        return Ok(());
    }
    let base = c
        .session
        .clone()
        .or(main_from_path)
        .ok_or("Claude record has no session identifier")?;
    let session = if c.sidechain {
        let agent = c
            .agent
            .clone()
            .or_else(|| path.file_stem().and_then(|s| s.to_str()).map(path_agent_id))
            .ok_or("subagent has no identifier")?;
        c.parent = if subagents.len() > 1 {
            subagents
                .last()
                .and_then(|i| i.checked_sub(1))
                .and_then(|i| components[i].as_os_str().to_str())
                .map(|parent| format!("{base}#agent:{}", path_agent_id(parent)))
        } else {
            Some(base.clone())
        };
        format!("{base}#agent:{agent}")
    } else {
        base
    };
    batch
        .sessions
        .push(metadata(c, Provider::Claude, session.clone()));
    if row.kind != "assistant" || row.api_error {
        return Ok(());
    }
    let Some(message) = row.message else {
        return Ok(());
    };
    if message.role.as_deref() != Some("assistant")
        || message.model.as_deref() == Some("<synthetic>")
    {
        return Ok(());
    }
    let Some(usage) = message.usage else {
        return Ok(());
    };
    c.usage_sequence += 1;
    let request = row.request_id.filter(|id| !id.is_empty());
    let message_id = message.id.or(row.uuid).filter(|id| !id.is_empty());
    let id = match (request, message_id) {
        (Some(request), Some(message)) => format!("request:{request}:{message}"),
        (Some(request), None) => format!("request:{request}"),
        (None, Some(message)) => format!("message:{session}:{message}"),
        (None, None) => format!("anonymous:{}", digest(&(session.clone(), path, c.usage_sequence))),
    };
    let time = timestamp(row.timestamp.as_deref()).ok();
    let (write5, write1) = usage
        .cache_creation
        .map(|v| (v.ephemeral_5m_input_tokens, v.ephemeral_1h_input_tokens))
        .unwrap_or((None, None));
    let ttl_total = write5
        .unwrap_or(0)
        .checked_add(write1.unwrap_or(0))
        .ok_or("token count overflow")?;
    let write = usage
        .cache_creation_input_tokens
        .map(|aggregate| aggregate.max(ttl_total))
        .or_else(|| (write5.is_some() || write1.is_some()).then_some(ttl_total));
    let total = usage
        .input_tokens
        .zip(usage.output_tokens)
        .map(|(a, b)| {
            a.checked_add(b)
                .and_then(|n| n.checked_add(usage.cache_read_input_tokens.unwrap_or(0)))
                .and_then(|n| n.checked_add(write.unwrap_or(0)))
                .ok_or_else(|| "token count overflow".to_string())
        })
        .transpose()?;
    let tokens = Tokens {
        input_uncached: usage.input_tokens,
        cache_read: usage.cache_read_input_tokens,
        cache_write: write,
        cache_write_5m: write5,
        cache_write_1h: write1,
        output: usage.output_tokens,
        reasoning: None,
        total,
    };
    batch.events.push(UsageEvent {
        uncertain_time: time.is_none().then_some(TimeBounds::default()),
        id,
        provider: Provider::Claude,
        session_id: session,
        timestamp_ms: time.unwrap_or(0),
        attribution: if message.model.is_some() {
            "reported"
        } else {
            "unknown"
        }
        .into(),
        model: message.model,
        model_provider: Some("anthropic".into()),
        revision_ms: None,
        incomplete: time.is_none() || tokens.input_uncached.is_none() || tokens.output.is_none()
            || usage.cache_creation_input_tokens.is_some_and(|aggregate| aggregate < ttl_total),
        tokens,
    });
    Ok(())
}
fn path_agent_id(name: &str) -> String {
    name.strip_prefix("agent-").unwrap_or(name).to_owned()
}
