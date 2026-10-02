use crate::model::*;
use serde::Deserialize;
use std::{collections::BTreeMap, path::Path};

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Rates {
    pub input: f64,
    pub cache_read: f64,
    pub cache_write_5m: Option<f64>,
    pub cache_write_1h: Option<f64>,
    pub output: f64,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LongContext {
    pub above_input_tokens: Option<u64>,
    pub rates: Rates,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ModelPrice {
    pub provider: Provider,
    pub rates: Rates,
    pub long_context: Option<LongContext>,
    /// Requests outside a documented model window cannot use its standard rate.
    pub max_input_tokens: Option<u64>,
    #[serde(default)]
    pub aliases: Vec<String>,
}

/// All rates are USD per million tokens, standard global API-equivalent pricing.
/// Rates are quantized to 1e-9 USD per million tokens before integer accumulation.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PricingCatalog {
    pub id: String,
    pub retrieved_at: String,
    pub sources: Vec<String>,
    pub models: BTreeMap<String, ModelPrice>,
}

/// Monetary fields use 1e-15 USD units so fractional nanodollars survive aggregation.
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
}

impl PricingCatalog {
    pub fn load(path: Option<&Path>) -> CoreResult<Self> {
        let content = match path {
            Some(path) => std::fs::read_to_string(path).map_err(|error| error.to_string())?,
            None => include_str!("../resources/pricing.json").to_owned(),
        };
        let catalog: Self = serde_json::from_str(&content)
            .map_err(|error| format!("Invalid pricing catalog: {error}"))?;
        if catalog.id.trim().is_empty()
            || catalog.retrieved_at.trim().is_empty()
            || catalog.sources.is_empty()
        {
            return Err("Pricing catalog requires id, retrieved_at and sources".into());
        }
        let mut names = std::collections::BTreeSet::new();
        for (name, price) in &catalog.models {
            validate_rates(&price.rates)?;
            if let Some(long) = &price.long_context {
                validate_rates(&long.rates)?;
            }
            for name in std::iter::once(name).chain(price.aliases.iter()) {
                if name.trim().is_empty() || !names.insert((price.provider.as_str(), name)) {
                    return Err(format!("Duplicate or empty pricing model name: {name}"));
                }
            }
        }
        Ok(catalog)
    }

    pub fn price(&self, event: &UsageEvent) -> EventCost {
        let tokens = &event.tokens;
        let write = cache_write_total(tokens);
        let input = tokens.input_uncached.unwrap_or(0);
        let read = tokens.cache_read.unwrap_or(0);
        let output = tokens.output.unwrap_or(0);
        let known_total = input
            .saturating_add(read)
            .saturating_add(write)
            .saturating_add(output);
        let total = tokens.total.unwrap_or(known_total).max(known_total);
        let mut cost = EventCost {
            total_tokens: total,
            ..EventCost::default()
        };
        let price = event.model.as_ref().and_then(|name| {
            self.models.iter().find_map(|(id, price)| {
                (price.provider == event.provider && (name == id || price.aliases.contains(name)))
                    .then_some(price)
            })
        });
        let Some(price) = price else {
            cost.unpriced = true;
            cost.uncertain = event.incomplete;
            cost.unknown_model = Some(event.model.clone().unwrap_or_else(|| "unknown".into()));
            return cost;
        };
        let all_input_known = tokens.input_uncached.is_some()
            && tokens.cache_read.is_some()
            && tokens.cache_write.is_some();
        let prompt = input.saturating_add(read).saturating_add(write);
        if price
            .max_input_tokens
            .is_some_and(|maximum| prompt > maximum)
        {
            cost.unpriced = true;
            cost.uncertain = true;
            return cost;
        }
        let mut rates = &price.rates;
        if let Some(long) = &price.long_context {
            if all_input_known
                && long
                    .above_input_tokens
                    .is_some_and(|threshold| prompt > threshold)
            {
                rates = &long.rates;
            }
            if !all_input_known || long.above_input_tokens.is_none() {
                cost.uncertain = true;
            }
        }
        cost.input_units = charge(input, rates.input);
        cost.read_units = charge(read, rates.cache_read);
        cost.output_units = charge(output, rates.output);
        let short_write = tokens.cache_write_5m.unwrap_or(0).min(write);
        let long_write = tokens
            .cache_write_1h
            .unwrap_or(0)
            .min(write.saturating_sub(short_write));
        let unknown_write = write.saturating_sub(short_write).saturating_sub(long_write);
        let write_rates_known = rates.cache_write_5m.is_some() && rates.cache_write_1h.is_some();
        let short_rate = rates.cache_write_5m.unwrap_or(0.0);
        let long_rate = rates.cache_write_1h.unwrap_or(0.0);
        let known_write_cost = charge(short_write, short_rate) + charge(long_write, long_rate);
        cost.write_min_units = known_write_cost + charge(unknown_write, short_rate.min(long_rate));
        cost.write_max_units = known_write_cost + charge(unknown_write, short_rate.max(long_rate));
        cost.uncertain |= event.incomplete
            || !all_input_known
            || tokens.output.is_none()
            || (write > 0 && !write_rates_known)
            || cost.write_min_units != cost.write_max_units
            || known_total != total;
        if let Some(long) = &price.long_context {
            if !all_input_known || long.above_input_tokens.is_none() {
                // Tier selection cannot be inferred from partial input metadata.
                // Bound the price of known categories; absent tokens stay unpriced.
                cost.uncertain = true;
                let higher = charge(input, long.rates.input)
                    + charge(read, long.rates.cache_read)
                    + charge(output, long.rates.output)
                    + charge(short_write, long.rates.cache_write_5m.unwrap_or(0.0))
                    + charge(long_write, long.rates.cache_write_1h.unwrap_or(0.0))
                    + charge(
                        unknown_write,
                        long.rates
                            .cache_write_5m
                            .unwrap_or(0.0)
                            .max(long.rates.cache_write_1h.unwrap_or(0.0)),
                    );
                let standard =
                    cost.input_units + cost.read_units + cost.output_units + cost.write_max_units;
                cost.tier_max_extra_units = higher.saturating_sub(standard);
            }
        }
        let unpriced_write = if write_rates_known { 0 } else { write };
        cost.priced_tokens = known_total.saturating_sub(unpriced_write);
        cost.unpriced = cost.priced_tokens < total || !all_input_known || tokens.output.is_none();
        cost
    }
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
    let nano_per_million = (usd_per_million * 1_000_000_000.0).round() as u128;
    u128::from(tokens) * nano_per_million
}

fn validate_rates(rates: &Rates) -> CoreResult<()> {
    for rate in [
        Some(rates.input),
        Some(rates.cache_read),
        rates.cache_write_5m,
        rates.cache_write_1h,
        Some(rates.output),
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
