use serde_json::{json, Value};
use tokencat_core::{model::*, pricing::PricingCatalog};

fn catalog(value: Value) -> PricingCatalog {
    PricingCatalog::from_json(&value.to_string(), "2026-10-02T12:00:00Z").unwrap()
}
fn rates(provider: &str, input: f64) -> Value {
    json!({"litellm_provider":provider,"mode":"chat","input_cost_per_token":input,
        "output_cost_per_token":input * 5.0,"cache_read_input_token_cost":input / 10.0,
        "cache_creation_input_token_cost":input * 1.25})
}
fn event(model: &str, provider: Option<&str>) -> UsageEvent {
    UsageEvent {
        uncertain_time: None,
        id: "event".into(),
        provider: Provider::OpenCode,
        session_id: "task".into(),
        timestamp_ms: 1,
        revision_ms: None,
        model: Some(model.into()),
        model_provider: provider.map(str::to_owned),
        attribution: "explicit".into(),
        incomplete: false,
        tokens: Tokens {
            input_uncached: Some(1000),
            cache_read: Some(100),
            cache_write: Some(0),
            output: Some(50),
            reasoning: Some(20),
            total: Some(1150),
            ..Tokens::default()
        },
    }
}

#[test]
fn bundled_snapshot_loads_and_covers_actual_opencode_deepseek_identity() {
    let catalog = PricingCatalog::load(None).unwrap();
    assert!(catalog.models.len() > 3000);
    assert!(catalog.id.starts_with("litellm-"));
    let cost = catalog.price(&event("deepseek-flash", Some("deepseek")));
    assert!(!cost.unpriced);
    assert_eq!(cost.pricing_match.unwrap().kind, "official");
}

#[test]
fn official_price_has_priority_over_recorded_reseller_and_explicit_reseller_key() {
    let catalog = catalog(json!({
        "gpt-example":rates("openai",0.000002),
        "openrouter/openai/gpt-example":rates("openrouter",0.000099)
    }));
    for name in [
        "gpt-example",
        "openai/gpt-example",
        "openrouter/openai/gpt-example",
    ] {
        let cost = catalog.price(&event(name, Some("openrouter")));
        assert_eq!(cost.input_units, 2_000_000_000_000);
        let matched = cost.pricing_match.unwrap();
        assert_eq!(matched.kind, "official");
        assert_eq!(matched.priced_model, "gpt-example");
        assert_eq!(matched.source, "openai");
    }
}

#[test]
fn third_party_source_is_explicit_and_ambiguous_choices_are_not_guessed() {
    let catalog = catalog(json!({
        "openrouter/openai/gpt-example":rates("openrouter",0.000003),
        "azure/gpt-example":rates("azure",0.000004)
    }));
    let cost = catalog.price(&event("gpt-example", Some("openrouter")));
    assert_eq!(cost.pricing_match.unwrap().kind, "third_party");
    assert_eq!(cost.input_units, 3_000_000_000_000);
    assert!(catalog.price(&event("gpt-example", None)).unpriced);
    let cost = catalog.price(&event("azure/gpt-example", None));
    assert_eq!(cost.pricing_match.unwrap().source, "azure");
    assert_eq!(cost.input_units, 4_000_000_000_000);
    let unique = super_catalog_single();
    assert_eq!(
        unique
            .price(&event("gpt-example", None))
            .pricing_match
            .unwrap()
            .kind,
        "third_party"
    );
}
fn super_catalog_single() -> PricingCatalog {
    catalog(json!({"openrouter/openai/gpt-example":rates("openrouter",0.000003)}))
}

#[test]
fn unknown_names_and_vendor_namespaces_never_match_by_resemblance() {
    let catalog = catalog(
        json!({"claude-sonnet-4-6":rates("anthropic",0.000003),"gpt-example":rates("openai",0.000002)}),
    );
    for model in [
        "claude-sonnet-4-6-private",
        "Qwen3.5-27B-Claude-4.6-Opus-Distilled-MLX-6bit",
        "anthropic/gpt-example",
    ] {
        let cost = catalog.price(&event(model, Some("omlx")));
        assert!(cost.unpriced, "{model}");
        assert_eq!(cost.priced_tokens, 0);
        assert_eq!(cost.unknown_model.as_deref(), Some(model));
        assert!(cost.pricing_match.is_none());
    }
}

#[test]
fn fixed_auto_review_policy_uses_luna_only_and_discloses_mapping() {
    let catalog = catalog(
        json!({"gpt-5.6-luna":rates("openai",0.0000002),"codex-auto-review":rates("openai",0.01)}),
    );
    let mut sample = event("codex-auto-review", None);
    sample.provider = Provider::Codex;
    let cost = catalog.price(&sample);
    assert_eq!(cost.input_units, 200_000_000_000);
    let matched = cost.pricing_match.unwrap();
    assert_eq!(matched.kind, "fixed");
    assert_eq!(matched.model, "codex-auto-review");
    assert_eq!(matched.priced_model, "gpt-5.6-luna");
    sample.provider = Provider::OpenCode;
    let from_opencode = catalog.price(&sample);
    assert_eq!(from_opencode.input_units, 200_000_000_000);
    assert_eq!(from_opencode.pricing_match.unwrap().kind, "fixed");
    let missing = catalog_without_luna();
    assert!(missing.price(&sample).unpriced);
    assert_eq!(
        missing.price(&sample).unknown_model.as_deref(),
        Some("codex-auto-review")
    );
}
fn catalog_without_luna() -> PricingCatalog {
    catalog(json!({"gpt-5.4-mini":rates("openai",0.00000075)}))
}

#[test]
fn model_identity_is_shared_across_harnesses_and_legacy_events_remain_supported() {
    let catalog = catalog(json!({"claude-example":rates("anthropic",0.000003)}));
    for harness in [
        Provider::Codex,
        Provider::Claude,
        Provider::OpenCode,
        Provider::Antigravity,
    ] {
        let mut sample = event("claude-example", None);
        sample.provider = harness;
        assert_eq!(catalog.price(&sample).input_units, 3_000_000_000_000);
    }
}

#[test]
fn zero_is_a_real_free_price_and_null_is_missing_coverage() {
    let catalog = catalog(json!({"free-model":rates("openai",0.0),"partial-model":{
        "litellm_provider":"openai","input_cost_per_token":0,"output_cost_per_token":null
    }}));
    let free = catalog.price(&event("free-model", Some("openai")));
    assert!(!free.unpriced);
    assert_eq!(free.priced_tokens, 1150);
    assert_eq!(free.input_units + free.output_units + free.read_units, 0);
    let partial = catalog.price(&event("partial-model", Some("openai")));
    assert!(partial.unpriced);
    assert_eq!(partial.priced_tokens, 1000);
    assert_eq!(partial.input_units, 0);
}

#[test]
fn all_standard_context_tiers_are_selected_and_priority_rates_are_ignored() {
    let mut row = rates("openai", 0.000001);
    for threshold in [32, 128, 200, 256, 272, 512] {
        row[format!("input_cost_per_token_above_{threshold}k_tokens")] =
            json!(threshold as f64 / 1_000_000.0);
        row[format!("output_cost_per_token_above_{threshold}k_tokens")] = json!(0.000005);
        row[format!("cache_read_input_token_cost_above_{threshold}k_tokens")] = json!(0.0000001);
    }
    row["input_cost_per_token_priority"] = json!(999999);
    row["input_cost_per_token_above_1k_tokens_priority"] = json!(999999);
    let catalog = catalog(json!({"gpt-example":row}));
    assert_eq!(catalog.models["gpt-example"].tiers.len(), 6);
    let mut sample = event("gpt-example", None);
    sample.tokens.cache_read = Some(0);
    sample.tokens.total = None;
    for threshold in [32_u64, 128, 200, 256, 272, 512] {
        sample.tokens.input_uncached = Some(threshold * 1000 + 1);
        let cost = catalog.price(&sample);
        assert_eq!(
            cost.input_units,
            u128::from(threshold * 1000 + 1) * u128::from(threshold) * 1_000_000_000
        );
        assert!(!cost.unpriced);
    }
    sample.tokens.input_uncached = Some(32000);
    assert_eq!(catalog.price(&sample).input_units, 32_000_000_000_000);
}

#[test]
fn missing_high_tier_cache_ttl_rate_never_reuses_low_tier() {
    let mut row = rates("anthropic", 0.000003);
    row["cache_creation_input_token_cost_above_1hr"] = json!(0.000006);
    row["input_cost_per_token_above_200k_tokens"] = json!(0.000006);
    row["output_cost_per_token_above_200k_tokens"] = json!(0.0000225);
    row["cache_read_input_token_cost_above_200k_tokens"] = json!(0.0000006);
    row["cache_creation_input_token_cost_above_200k_tokens"] = json!(0.0000075);
    let catalog = catalog(json!({"claude-example":row}));
    let mut sample = event("claude-example", None);
    sample.tokens.input_uncached = Some(200001);
    sample.tokens.cache_write = Some(100);
    sample.tokens.cache_write_5m = Some(40);
    sample.tokens.cache_write_1h = Some(60);
    sample.tokens.total = None;
    let cost = catalog.price(&sample);
    assert!(cost.unpriced);
    assert_eq!(cost.priced_tokens, cost.total_tokens - 60);
    assert_eq!(cost.write_min_units, 300_000_000_000);
    assert_eq!(
        catalog.models["claude-example"].tiers[0]
            .rates
            .cache_write_1h,
        None
    );
}

#[test]
fn unknown_ttl_has_bounds_when_both_rates_exist_and_reasoning_is_not_added_twice() {
    let mut row = rates("anthropic", 0.000003);
    row["cache_creation_input_token_cost_above_1hr"] = json!(0.000006);
    let catalog = catalog(json!({"claude-example":row}));
    let mut sample = event("claude-example", None);
    sample.tokens.cache_write = Some(100);
    sample.tokens.total = None;
    let cost = catalog.price(&sample);
    assert_eq!(cost.write_min_units, 375_000_000_000);
    assert_eq!(cost.write_max_units, 600_000_000_000);
    assert_eq!(cost.output_units, 750_000_000_000);
    assert_eq!(cost.priced_tokens, 1250);
    assert!(!cost.unpriced);
    assert!(cost.uncertain);
}

#[test]
fn cache_envelope_preserves_canonical_identity_and_actual_retrieval_date() {
    let raw = json!({"gpt-example":rates("openai",0.000002)});
    let first = catalog(raw.clone());
    let wrapped=PricingCatalog::from_json(&json!({"tokencat_litellm_cache":1,
        "retrieved_at":"2026-10-01T10:00:00Z","catalog":raw,"checked_at":"2026-10-02T11:00:00Z","etag":"v1","catalog_id":first.id}).to_string(),"unused").unwrap();
    assert_eq!(first.id, wrapped.id);
    assert_eq!(wrapped.retrieved_at, "2026-10-01T10:00:00Z");
    let compact=PricingCatalog::from_json("{\"gpt-example\":{\"output_cost_per_token\":0,\"litellm_provider\":\"openai\",\"input_cost_per_token\":0}}","now").unwrap();
    let reordered=PricingCatalog::from_json("{\"gpt-example\":{\"litellm_provider\":\"openai\",\"input_cost_per_token\":0,\"output_cost_per_token\":0}}","now").unwrap();
    assert_eq!(compact.id, reordered.id);
    let floats=PricingCatalog::from_json("{\"gpt-example\":{\"litellm_provider\":\"openai\",\"input_cost_per_token\":0.0,\"output_cost_per_token\":0.0}}","now").unwrap();
    assert_eq!(compact.id, floats.id);
    let original="{\"gpt-example\":{\"litellm_provider\":\"openai\",\"input_cost_per_token\":0.000002,\"output_cost_per_token\":0.00001,\"cache_read_input_token_cost\":0.0000002}}";
    let raw_catalog = PricingCatalog::from_json(original, "2026-10-02T12:00:00Z").unwrap();
    let text_envelope = json!({"tokencat_litellm_cache":1,"retrieved_at":"2026-10-02T12:00:00Z","catalog":original});
    let text_catalog = PricingCatalog::from_json(&text_envelope.to_string(), "unused").unwrap();
    assert_eq!(raw_catalog.id, text_catalog.id);
}

#[test]
fn invalid_catalogs_fail_validation_instead_of_silently_replacing_prices() {
    for raw in [
        "{}",
        "[]",
        "broken",
        "{\"error\":\"not found\"}",
        "{\"tokencat_litellm_cache\":2,\"catalog\":{}}",
        "{\"gpt-example\":{\"litellm_provider\":\"openai\",\"input_cost_per_token\":-1}}",
        "{\"gpt-example\":{\"litellm_provider\":\"openai\",\"input_cost_per_token\":\"private\"}}",
    ] {
        assert!(PricingCatalog::from_json(raw, "now").is_err(), "{raw}");
    }
}

#[test]
fn unknown_vendors_do_not_cross_match_same_private_model_name() {
    let catalog = catalog(json!({"provider-b/private-model":rates("provider-b",0.000003)}));
    assert!(
        catalog
            .price(&event("private-model", Some("provider-a")))
            .unpriced
    );
    assert!(
        !catalog
            .price(&event("private-model", Some("provider-b")))
            .unpriced
    );
    assert!(
        !catalog
            .price(&event("provider-b/private-model", Some("provider-b")))
            .unpriced
    );
}

#[test]
fn tier_tables_keep_official_qwen_prices_and_enforce_ranges() {
    let catalog = PricingCatalog::load(None).unwrap();
    let mut sample = event("qwen3-coder-plus", Some("dashscope"));
    sample.tokens.cache_read = Some(0);
    sample.tokens.total = None;
    for (input, rate) in [
        (32000_u64, 1.0_f64),
        (32001, 1.8),
        (128001, 3.0),
        (256001, 6.0),
    ] {
        sample.tokens.input_uncached = Some(input);
        let cost = catalog.price(&sample);
        assert_eq!(cost.pricing_match.unwrap().source, "dashscope");
        assert_eq!(
            cost.input_units,
            u128::from(input) * (rate * 1_000_000_000.0).round() as u128
        );
        assert!(!cost.unpriced);
    }
    sample.tokens.input_uncached = Some(1_000_001);
    assert!(catalog.price(&sample).unpriced);
}

#[test]
fn explicit_reasoning_rate_prices_the_output_subset_once() {
    let mut row = rates("dashscope", 0.000001);
    row["output_cost_per_reasoning_token"] = json!(0.000010);
    let catalog = catalog(json!({"dashscope/qwen-example":row}));
    let mut sample = event("qwen-example", Some("dashscope"));
    let cost = catalog.price(&sample);
    assert_eq!(cost.output_units, 350_000_000_000);
    assert_eq!(cost.priced_tokens, 1150);
    sample.tokens.reasoning = None;
    let cost = catalog.price(&sample);
    assert_eq!(cost.output_units, 250_000_000_000);
    assert_eq!(cost.tier_max_extra_units, 250_000_000_000);
    assert!(cost.uncertain);
}

#[test]
fn bedrock_anthropic_default_write_does_not_fabricate_one_hour_price() {
    let name = "anthropic.claude-sonnet-4-20250514-v1:0";
    let catalog = catalog(json!({name:rates("bedrock_converse",0.000003)}));
    let mut sample = event(name, Some("bedrock_converse"));
    sample.tokens.cache_write = Some(100);
    sample.tokens.cache_write_5m = Some(0);
    sample.tokens.cache_write_1h = Some(100);
    sample.tokens.total = None;
    let cost = catalog.price(&sample);
    assert!(cost.unpriced);
    assert_eq!(cost.priced_tokens, cost.total_tokens - 100);
    assert_eq!(cost.write_min_units, 0);
}

#[test]
fn reported_total_without_categories_gets_an_upper_cost_without_invented_buckets() {
    let prices = catalog(json!({"gpt-example":rates("openai",0.000002)}));
    let mut sample = event("gpt-example",Some("openai"));
    sample.tokens = Tokens { total: Some(1000), ..Tokens::default() };
    let cost = prices.price(&sample);
    assert_eq!(cost.total_tokens,1000);
    assert_eq!(cost.priced_tokens,0);
    assert_eq!(cost.input_units,0);
    assert_eq!(cost.output_units,0);
    // Highest model rate is output at $10/million; no fabricated input/output counts.
    assert_eq!(cost.tier_max_extra_units,10_000_000_000_000);
    assert!(cost.uncertain && cost.unpriced);
    let mut unknown = sample;
    unknown.model=Some("unidentified-model".into());
    assert_eq!(prices.price(&unknown).tier_max_extra_units,0);
}
