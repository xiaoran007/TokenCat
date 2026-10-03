use crate::model::*;
use serde::Deserialize;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
};

const LITELLM_SOURCE: &str =
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json";

/// USD per million tokens. None means absent pricing; Some(0) means free.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Rates {
    pub input: Option<f64>,
    pub cache_read: Option<f64>,
    pub cache_write_5m: Option<f64>,
    pub cache_write_1h: Option<f64>,
    pub output: Option<f64>,
    pub reasoning: Option<f64>,
}
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LongContext {
    pub above_input_tokens: Option<u64>,
    pub rates: Rates,
}
#[derive(Debug, Clone)]
pub struct ModelPrice {
    pub provider: String,
    pub rates: Rates,
    pub tiers: Vec<LongContext>,
    pub max_input_tokens: Option<u64>,
    pub aliases: Vec<String>,
}
#[derive(Debug, Clone)]
pub struct PricingCatalog {
    pub id: String,
    pub retrieved_at: String,
    pub sources: Vec<String>,
    pub models: BTreeMap<String, ModelPrice>,
    identities: BTreeMap<(Option<String>, String), Vec<String>>,
}
/// Monetary fields use 1e-15 USD units, accumulating before display rounding.
#[derive(Debug, Clone, Default)]
pub struct EventCost {
    pub input_units: u128,
    pub read_units: u128,
    pub write_min_units: u128,
    pub write_max_units: u128,
    pub output_units: u128,
    pub tier_max_extra_units: u128,
    pub priced_tokens: u64,
    pub total_tokens: u64,
    pub unpriced: bool,
    pub uncertain: bool,
    pub unknown_model: Option<String>,
    pub pricing_match: Option<PricingMatch>,
}
impl EventCost {
    fn minimum(&self) -> u128 {
        self.input_units + self.read_units + self.write_min_units + self.output_units
    }
    fn maximum(&self) -> u128 {
        self.input_units
            + self.read_units
            + self.write_max_units
            + self.output_units
            + self.tier_max_extra_units
    }
}

impl PricingCatalog {
    pub fn load(path: Option<&Path>) -> CoreResult<Self> {
        match path {
            Some(path) => {
                let content = std::fs::read_to_string(path).map_err(|error| error.to_string())?;
                let modified: chrono::DateTime<chrono::Utc> = std::fs::metadata(path)
                    .and_then(|metadata| metadata.modified())
                    .map_err(|error| error.to_string())?
                    .into();
                Self::from_json(&content, &modified.to_rfc3339())
            }
            None => {
                let metadata: Value =
                    serde_json::from_str(include_str!("../resources/litellm-metadata.json"))
                        .map_err(|error| error.to_string())?;
                Self::from_json(
                    include_str!("../resources/litellm.json"),
                    metadata["retrieved_at"]
                        .as_str()
                        .ok_or("Bundled catalog has no retrieval date")?,
                )
            }
        }
    }

    /// Raw LiteLLM, its explicitly tagged atomic cache, or an existing native
    /// custom catalog. Invalid input never silently selects the bundled default.
    pub fn from_json(content: &str, retrieved_at: &str) -> CoreResult<Self> {
        let mut document: Value =
            serde_json::from_str(content).map_err(|_| "Invalid pricing catalog JSON")?;
        let mut date = retrieved_at.to_owned();
        if document.get("tokencat_litellm_cache").is_some() {
            if document["tokencat_litellm_cache"].as_u64() != Some(1) {
                return Err("Unsupported LiteLLM cache version".into());
            }
            date = document["retrieved_at"]
                .as_str()
                .filter(|date| !date.is_empty())
                .ok_or("LiteLLM cache requires retrieved_at")?
                .into();
            document = document
                .get("catalog")
                .cloned()
                .ok_or("LiteLLM cache requires catalog")?;
            if let Value::String(raw) = document {
                document = serde_json::from_str(&raw)
                    .map_err(|_| "Invalid cached LiteLLM catalog JSON")?;
            }
        }
        if document.get("models").is_some() || document.get("id").is_some() {
            return Self::legacy(document);
        }
        if date.trim().is_empty() {
            return Err("Pricing catalog requires retrieved_at".into());
        }
        let rows = document
            .as_object()
            .ok_or("LiteLLM catalog must be an object")?;
        let mut models = BTreeMap::new();
        for (name, row) in rows {
            if name == "sample_spec" {
                continue;
            }
            let Some(row) = row.as_object() else {
                return Err("Invalid LiteLLM model record".into());
            };
            let Some(provider) = row
                .get("litellm_provider")
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty())
            else {
                continue;
            };
            if row
                .get("mode")
                .and_then(Value::as_str)
                .is_some_and(|mode| !matches!(mode, "chat" | "completion" | "responses"))
            {
                continue;
            }
            let provider = service(provider).to_owned();
            let ttl = identity(name, &provider).0.as_deref() == Some("anthropic")
                || (matches!(
                    provider.as_str(),
                    "bedrock" | "bedrock_converse" | "bedrock_mantle"
                ) && (name.starts_with("anthropic.claude-")
                    || name.contains("/anthropic.claude-")
                    || name.contains(".anthropic.claude-")))
                || row
                    .keys()
                    .any(|key| key.starts_with("cache_creation_input_token_cost_above_1hr"));
            let mut rates = parse_rates(row, "", ttl)?;
            let mut thresholds = BTreeSet::new();
            for key in row.keys() {
                for prefix in [
                    "input_cost_per_token_above_",
                    "output_cost_per_token_above_",
                    "cache_read_input_token_cost_above_",
                    "cache_creation_input_token_cost_above_",
                ] {
                    if let Some(number) = key
                        .strip_prefix(prefix)
                        .and_then(|suffix| suffix.strip_suffix("k_tokens"))
                    {
                        if let Ok(number) = number.parse::<u64>() {
                            thresholds.insert(
                                number
                                    .checked_mul(1000)
                                    .ok_or("Invalid context threshold")?,
                            );
                        }
                    }
                }
            }
            let mut tiers = thresholds
                .into_iter()
                .map(|threshold| {
                    Ok(LongContext {
                        above_input_tokens: Some(threshold),
                        rates: parse_rates(
                            row,
                            &format!("_above_{}k_tokens", threshold / 1000),
                            ttl,
                        )?,
                    })
                })
                .collect::<CoreResult<Vec<_>>>()?;
            let mut max_input_tokens = row
                .get("max_input_tokens")
                .and_then(Value::as_u64)
                .filter(|value| *value > 0);
            if let Some(table) = row.get("tiered_pricing") {
                let (base, ranged, maximum) = parse_range_tiers(table, ttl)?;
                rates = base;
                tiers = ranged;
                max_input_tokens =
                    Some(max_input_tokens.map_or(maximum, |limit| limit.min(maximum)));
            }
            if rates.input.is_none() && rates.output.is_none() {
                continue;
            }
            models.insert(
                name.clone(),
                ModelPrice {
                    provider,
                    rates,
                    tiers,
                    max_input_tokens,
                    aliases: vec![],
                },
            );
        }
        if models.is_empty() {
            return Err("LiteLLM catalog has no usable token prices".into());
        }
        let canonical =
            serde_json::to_vec(&canonical_numbers(document)).map_err(|error| error.to_string())?;
        let hash = format!("{:x}", Sha256::digest(canonical));
        Ok(Self {
            id: format!("litellm-{}", &hash[..16]),
            retrieved_at: date,
            sources: vec![LITELLM_SOURCE.into()],
            identities: index(&models),
            models,
        })
    }

    fn legacy(document: Value) -> CoreResult<Self> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct LegacyPrice {
            provider: String,
            rates: Rates,
            long_context: Option<LongContext>,
            max_input_tokens: Option<u64>,
            #[serde(default)]
            aliases: Vec<String>,
        }
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct LegacyCatalog {
            id: String,
            retrieved_at: String,
            sources: Vec<String>,
            models: BTreeMap<String, LegacyPrice>,
        }
        let old: LegacyCatalog =
            serde_json::from_value(document).map_err(|_| "Invalid native pricing catalog")?;
        if old.id.trim().is_empty()
            || old.retrieved_at.trim().is_empty()
            || old.sources.is_empty()
            || old.models.is_empty()
        {
            return Err("Pricing catalog requires id, retrieved_at, sources and models".into());
        }
        let mut models = BTreeMap::new();
        let mut names = BTreeSet::new();
        for (name, price) in old.models {
            let provider = service(&price.provider).to_owned();
            if !matches!(price.provider.as_str(), "codex" | "claude") {
                return Err("Native catalog provider must be codex or claude; use LiteLLM format for other services".into());
            }
            for name in std::iter::once(&name).chain(price.aliases.iter()) {
                if name.trim().is_empty() || !names.insert((provider.clone(), name.clone())) {
                    return Err("Duplicate or empty pricing model name".into());
                }
            }
            validate_rates(&price.rates)?;
            if let Some(tier) = &price.long_context {
                validate_rates(&tier.rates)?;
            }
            models.insert(
                name,
                ModelPrice {
                    provider,
                    rates: price.rates,
                    tiers: price.long_context.into_iter().collect(),
                    max_input_tokens: price.max_input_tokens,
                    aliases: price.aliases,
                },
            );
        }
        Ok(Self {
            id: old.id,
            retrieved_at: old.retrieved_at,
            sources: old.sources,
            identities: index(&models),
            models,
        })
    }

    fn resolve<'a>(
        &'a self,
        event: &UsageEvent,
    ) -> Option<(&'a str, &'a ModelPrice, &'static str)> {
        let observed = event.model.as_deref()?;
        if observed == "codex-auto-review" {
            // Explicit user policy; no other substitute when Luna is unavailable.
            return self
                .models
                .iter()
                .find(|(key, value)| {
                    value.provider == "openai" && identity(key, &value.provider).1 == "gpt-5.6-luna"
                })
                .map(|(key, value)| (key.as_str(), value, "fixed"));
        }
        let source = event
            .model_provider
            .as_deref()
            .map(service)
            .unwrap_or(match event.provider {
                Provider::Codex => "openai",
                Provider::Claude => "anthropic",
                _ => "",
            });
        let identity_source = self
            .models
            .get(observed)
            .filter(|_| observed.contains('/'))
            .map_or(source, |price| price.provider.as_str());
        let (vendor, model) = identity(observed, identity_source);
        let candidates: Vec<_> = self
            .identities
            .get(&(vendor.clone(), model.to_owned()))?
            .iter()
            .filter_map(|key| self.models.get(key).map(|value| (key.as_str(), value)))
            .collect();
        let mut official: Vec<_> = candidates
            .iter()
            .copied()
            .filter(|(_, value)| {
                vendor
                    .as_deref()
                    .is_some_and(|vendor| service(&value.provider) == vendor)
            })
            .collect();
        official.sort_by_key(|(key, _)| (usize::from(*key != model), *key));
        if let Some((key, value)) = official.first() {
            return Some((*key, *value, "official"));
        }
        if let Some((key, value)) = candidates.iter().find(|(key, _)| *key == observed) {
            // An explicit namespace selects its source; a bare ID does not.
            if observed.contains('/') || value.provider == source {
                return Some((*key, *value, "third_party"));
            }
        }
        let matching_source: Vec<_> = candidates
            .iter()
            .copied()
            .filter(|(_, value)| value.provider == source)
            .collect();
        if let Some((key, value)) = matching_source
            .first()
            .filter(|_| matching_source.len() == 1)
        {
            return Some((*key, *value, "third_party"));
        }
        if vendor.is_some() && candidates.len() == 1 {
            let (key, value) = candidates[0];
            return Some((key, value, "third_party"));
        }
        None
    }

    pub fn price(&self, event: &UsageEvent) -> EventCost {
        let tokens = &event.tokens;
        let known_total = tokens.known_total();
        let total = tokens.total.unwrap_or(known_total).max(known_total);
        let unallocated = total.saturating_sub(known_total);
        let missing = || EventCost {
            total_tokens: total,
            unpriced: true,
            uncertain: event.incomplete,
            unknown_model: Some(event.model.clone().unwrap_or_else(|| "unknown".into())),
            ..EventCost::default()
        };
        let Some((key, price, kind)) = self.resolve(event) else {
            return missing();
        };
        let input_known = tokens.input_uncached.is_some()
            && tokens.cache_read.is_some()
            && (tokens.cache_write.is_some()
                || (tokens.cache_write_5m.is_some() && tokens.cache_write_1h.is_some()));
        let prompt = tokens
            .input_uncached
            .unwrap_or(0)
            .saturating_add(tokens.cache_read.unwrap_or(0))
            .saturating_add(cache_write_total(tokens));
        if price
            .max_input_tokens
            .is_some_and(|maximum| prompt > maximum)
        {
            return EventCost {
                uncertain: true,
                ..missing()
            };
        }
        let ambiguous = !price.tiers.is_empty()
            && (!input_known || unallocated > 0
                || price
                    .tiers
                    .iter()
                    .any(|tier| tier.above_input_tokens.is_none()));
        let mut cost = if ambiguous {
            let variants: Vec<_> = std::iter::once(&price.rates)
                .chain(price.tiers.iter().map(|tier| &tier.rates))
                .map(|rates| price_rates(tokens, rates))
                .collect();
            let max = variants.iter().map(EventCost::maximum).max().unwrap();
            let coverage = variants
                .iter()
                .map(|cost| cost.priced_tokens)
                .min()
                .unwrap();
            let mut min = variants
                .iter()
                .min_by_key(|cost| cost.minimum())
                .unwrap()
                .clone();
            min.tier_max_extra_units += max.saturating_sub(min.maximum());
            min.priced_tokens = coverage;
            min.uncertain = true;
            min
        } else {
            let rates = price
                .tiers
                .iter()
                .rev()
                .find(|tier| {
                    tier.above_input_tokens
                        .is_some_and(|threshold| prompt > threshold)
                })
                .map_or(&price.rates, |tier| &tier.rates);
            price_rates(tokens, rates)
        };
        cost.total_tokens = total;
        // A reported total can outlive its category breakdown. Preserve that
        // total and price its unallocated portion at the highest applicable
        // model rate for the upper estimate, without inventing token categories.
        if unallocated > 0 {
            let rate = std::iter::once(&price.rates).chain(price.tiers.iter().map(|tier| &tier.rates))
                .flat_map(|rates| [rates.input, rates.cache_read, rates.cache_write_5m,
                    rates.cache_write_1h, rates.output, rates.reasoning])
                .flatten().max_by(f64::total_cmp);
            if let Some(rate) = rate {
                cost.tier_max_extra_units += charge(unallocated, rate);
            }
        }
        cost.uncertain |=
            event.incomplete || event.uncertain_time.is_some() || !input_known || tokens.output.is_none() || known_total != total;
        cost.unpriced = cost.priced_tokens < total || !input_known || tokens.output.is_none();
        cost.pricing_match = Some(PricingMatch {
            model: event.model.clone().unwrap(),
            priced_model: key.into(),
            source: price.provider.clone(),
            kind: kind.into(),
        });
        cost
    }
}

fn parse_rates(row: &Map<String, Value>, suffix: &str, ttl: bool) -> CoreResult<Rates> {
    let value = |base: &str| -> CoreResult<Option<f64>> {
        match row.get(&format!("{base}{suffix}")) {
            None | Some(Value::Null) => Ok(None),
            Some(value) => value
                .as_f64()
                .map(|value| value * 1_000_000.0)
                .map(Some)
                .ok_or("Invalid LiteLLM token rate".into()),
        }
    };
    let write = value("cache_creation_input_token_cost")?;
    let rates = Rates {
        input: value("input_cost_per_token")?,
        cache_read: value("cache_read_input_token_cost")?,
        cache_write_5m: write,
        // Generic writes have no TTL premium. Anthropic's absent 1h price stays unknown.
        cache_write_1h: if ttl {
            value("cache_creation_input_token_cost_above_1hr")?
        } else {
            write
        },
        output: value("output_cost_per_token")?,
        reasoning: value("output_cost_per_reasoning_token")?,
    };
    validate_rates(&rates)?;
    Ok(rates)
}

fn parse_range_tiers(value: &Value, ttl: bool) -> CoreResult<(Rates, Vec<LongContext>, u64)> {
    let rows = value
        .as_array()
        .filter(|rows| !rows.is_empty())
        .ok_or("Invalid LiteLLM tier table")?;
    let mut end = 0;
    let mut base = None;
    let mut tiers = Vec::new();
    for row in rows {
        let row = row.as_object().ok_or("Invalid LiteLLM tier")?;
        let bounds = row
            .get("range")
            .and_then(Value::as_array)
            .filter(|range| range.len() == 2)
            .ok_or("Invalid LiteLLM tier range")?;
        let integer = |value: &Value| -> CoreResult<u64> {
            let value = value.as_f64().ok_or("Invalid LiteLLM tier boundary")?;
            if !value.is_finite()
                || value < 0.0
                || value > (1_u64 << 53) as f64
                || value.fract() != 0.0
            {
                return Err("Invalid LiteLLM tier boundary".into());
            }
            Ok(value as u64)
        };
        let start = integer(&bounds[0])?;
        let next = integer(&bounds[1])?;
        if start != end || next <= start {
            return Err("LiteLLM tier ranges must be ordered and contiguous from zero".into());
        }
        let rates = parse_rates(row, "", ttl)?;
        if start == 0 {
            base = Some(rates);
        } else {
            tiers.push(LongContext {
                above_input_tokens: Some(start),
                rates,
            });
        }
        end = next;
    }
    Ok((
        base.ok_or("LiteLLM tier table requires a base range")?,
        tiers,
        end,
    ))
}

// Foundation rewrites JSON 0.0 to 0 when storing an envelope. Normalize number
// representation as well as sorted object keys so the catalog ID remains stable.
fn canonical_numbers(value: Value) -> Value {
    match value {
        Value::Number(number) => number
            .as_f64()
            .and_then(serde_json::Number::from_f64)
            .map(Value::Number)
            .unwrap_or(Value::Number(number)),
        Value::Array(values) => Value::Array(values.into_iter().map(canonical_numbers).collect()),
        Value::Object(values) => Value::Object(
            values
                .into_iter()
                .map(|(key, value)| (key, canonical_numbers(value)))
                .collect(),
        ),
        value => value,
    }
}

fn service(value: &str) -> &str {
    match value {
        "codex" | "text-completion-openai" => "openai",
        "claude" => "anthropic",
        "google" => "gemini",
        "x-ai" => "xai",
        "mistralai" | "codestral" | "text-completion-codestral" => "mistral",
        "moonshotai" => "moonshot",
        "z-ai" => "zai",
        "qwen" | "qwen_ai_platform" => "dashscope",
        other => other,
    }
}
fn vendor_for_model(model: &str) -> Option<&'static str> {
    if model.starts_with("gpt-")
        || model.starts_with("chatgpt-")
        || model.starts_with("codex-")
        || ["o1", "o3", "o4"]
            .iter()
            .any(|prefix| model == *prefix || model.starts_with(&format!("{prefix}-")))
    {
        Some("openai")
    } else if model.starts_with("claude-") {
        Some("anthropic")
    } else if model.starts_with("gemini-") {
        Some("gemini")
    } else if model.starts_with("deepseek-") {
        Some("deepseek")
    } else if model.starts_with("grok-") {
        Some("xai")
    } else if [
        "mistral-",
        "codestral-",
        "devstral-",
        "ministral-",
        "magistral-",
    ]
    .iter()
    .any(|prefix| model.starts_with(prefix))
    {
        Some("mistral")
    } else if model.starts_with("kimi-") || model.starts_with("moonshot-") {
        Some("moonshot")
    } else if model.starts_with("glm-") {
        Some("zai")
    } else if model.starts_with("MiniMax-") || model.starts_with("minimax-") {
        Some("minimax")
    } else if model.starts_with("qwen-")
        || model.starts_with("qwen3-")
        || model.starts_with("qwen3.5-")
    {
        Some("dashscope")
    } else {
        None
    }
}
fn official_source(source: &str) -> bool {
    matches!(
        source,
        "openai"
            | "anthropic"
            | "gemini"
            | "deepseek"
            | "xai"
            | "mistral"
            | "moonshot"
            | "zai"
            | "minimax"
            | "dashscope"
            | "cohere"
            | "ai21"
            | "perplexity"
            | "inception"
            | "xiaomi_mimo"
    )
}
/// Strip explicit provider namespaces only; retain exact version/date suffixes.
fn identity<'a>(name: &'a str, source: &str) -> (Option<String>, &'a str) {
    let mut name = name;
    if let Some((prefix, rest)) = name.split_once('/') {
        if service(prefix) == source
            || matches!(
                prefix,
                "openrouter"
                    | "azure"
                    | "vercel_ai_gateway"
                    | "aihubmix"
                    | "together_ai"
                    | "fireworks_ai"
                    | "deepinfra"
            )
        {
            name = rest;
        }
    }
    if let Some((prefix, rest)) = name.split_once('/') {
        let vendor = service(prefix);
        if official_source(vendor) {
            return (Some(vendor.into()), rest);
        }
    }
    let vendor = vendor_for_model(name)
        .map(str::to_owned)
        .or_else(|| official_source(source).then(|| source.to_owned()));
    (vendor, name)
}

fn index(models: &BTreeMap<String, ModelPrice>) -> BTreeMap<(Option<String>, String), Vec<String>> {
    let mut result: BTreeMap<_, Vec<String>> = BTreeMap::new();
    for (key, price) in models {
        for name in std::iter::once(key.as_str()).chain(price.aliases.iter().map(String::as_str)) {
            let (vendor, model) = identity(name, &price.provider);
            let entries = result.entry((vendor, model.to_owned())).or_default();
            if !entries.contains(key) {
                entries.push(key.clone());
            }
        }
    }
    result
}

fn price_rates(tokens: &Tokens, rates: &Rates) -> EventCost {
    let mut cost = EventCost::default();
    fn category(tokens: u64, rate: Option<f64>, cost: &mut EventCost) -> u128 {
        if let Some(rate) = rate {
            cost.priced_tokens = cost.priced_tokens.saturating_add(tokens);
            charge(tokens, rate)
        } else {
            cost.uncertain |= tokens > 0;
            0
        }
    }
    cost.input_units = category(tokens.input_uncached.unwrap_or(0), rates.input, &mut cost);
    cost.read_units = category(tokens.cache_read.unwrap_or(0), rates.cache_read, &mut cost);
    if let Some(reasoning_rate) = rates.reasoning {
        let output = tokens.output.unwrap_or(0);
        match tokens.reasoning {
            Some(reasoning) if reasoning <= output => {
                cost.output_units = category(output - reasoning, rates.output, &mut cost)
                    + category(reasoning, Some(reasoning_rate), &mut cost);
            }
            None if rates.output.is_some() => {
                let output_rate = rates.output.unwrap();
                cost.output_units =
                    category(output, Some(output_rate.min(reasoning_rate)), &mut cost);
                cost.tier_max_extra_units = charge(output, output_rate.max(reasoning_rate))
                    .saturating_sub(cost.output_units);
                cost.uncertain |= output > 0 && output_rate != reasoning_rate;
            }
            _ => {
                cost.uncertain = true;
            }
        }
    } else {
        cost.output_units = category(tokens.output.unwrap_or(0), rates.output, &mut cost);
    }
    let write = cache_write_total(tokens);
    let short = tokens.cache_write_5m.unwrap_or(0).min(write);
    let long = tokens
        .cache_write_1h
        .unwrap_or(0)
        .min(write.saturating_sub(short));
    let unknown = write.saturating_sub(short).saturating_sub(long);
    let known = category(short, rates.cache_write_5m, &mut cost)
        + category(long, rates.cache_write_1h, &mut cost);
    cost.write_min_units = known;
    cost.write_max_units = known;
    if unknown > 0 {
        if let Some((short, long)) = rates.cache_write_5m.zip(rates.cache_write_1h) {
            cost.write_min_units += charge(unknown, short.min(long));
            cost.write_max_units += charge(unknown, short.max(long));
            cost.priced_tokens = cost.priced_tokens.saturating_add(unknown);
            cost.uncertain |= short != long;
        } else {
            cost.uncertain = true;
        }
    }
    cost
}
pub fn cache_write_total(tokens: &Tokens) -> u64 {
    tokens.cache_write.unwrap_or_else(|| {
        tokens
            .cache_write_5m
            .unwrap_or(0)
            .saturating_add(tokens.cache_write_1h.unwrap_or(0))
    })
}
fn charge(tokens: u64, usd_per_million: f64) -> u128 {
    u128::from(tokens) * (usd_per_million * 1_000_000_000.0).round() as u128
}
fn validate_rates(rates: &Rates) -> CoreResult<()> {
    for rate in [
        rates.input,
        rates.cache_read,
        rates.cache_write_5m,
        rates.cache_write_1h,
        rates.output,
        rates.reasoning,
    ]
    .into_iter()
    .flatten()
    {
        if !rate.is_finite() || !(0.0..=1_000_000.0).contains(&rate) {
            return Err("Pricing rates must be finite nonnegative USD amounts below 1,000,000 per million tokens".into());
        }
    }
    Ok(())
}
