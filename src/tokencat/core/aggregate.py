from __future__ import annotations

from collections import defaultdict
from datetime import date

from tokencat.core.models import CostEstimate, DailyUsageRecord, ModelUsage, PricingCoverage, ProviderName, SessionRecord, TokenTotals


def aggregate_summary(records: list[SessionRecord], *, pricing_coverage: PricingCoverage | None = None) -> dict[str, object]:
    totals = TokenTotals.zero()
    provider_totals: dict[str, dict[str, object]] = {}
    overall_models: set[str] = set()
    total_cost = CostEstimate()

    by_provider: dict[ProviderName, list[SessionRecord]] = defaultdict(list)
    for record in records:
        by_provider[record.provider].append(record)
        totals.add(record.token_totals)
        overall_models.update(record.models)
        if record.estimated_cost is not None:
            total_cost.add(record.estimated_cost)

    for provider, provider_records in sorted(by_provider.items(), key=lambda item: item[0].value):
        provider_tokens = TokenTotals.zero()
        provider_models: set[str] = set()
        provider_cost = CostEstimate()
        for record in provider_records:
            provider_tokens.add(record.token_totals)
            provider_models.update(record.models)
            if record.estimated_cost is not None:
                provider_cost.add(record.estimated_cost)
        provider_totals[provider.value] = {
            "session_count": len(provider_records),
            "model_count": len(provider_models),
            "token_totals": provider_tokens.to_dict(),
            "estimated_cost": provider_cost.to_dict(),
        }

    summary = {
        "session_count": len(records),
        "model_count": len(overall_models),
        "token_totals": totals.to_dict(),
        "estimated_cost": total_cost.to_dict(),
        "providers": provider_totals,
    }
    if pricing_coverage is not None:
        summary["pricing_coverage"] = pricing_coverage.to_dict()
    return summary


def aggregate_models(records: list[SessionRecord]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str], ModelUsage] = {}
    sessions_per_model: dict[tuple[str, str], set[str]] = defaultdict(set)
    attribution_statuses: dict[tuple[str, str], set[str]] = defaultdict(set)
    pricing_models: dict[tuple[str, str], set[str]] = defaultdict(set)
    fallback_flags: dict[tuple[str, str], bool] = defaultdict(bool)

    for record in records:
        for model_name, usage in record.model_usage.items():
            key = (record.provider.value, model_name)
            bucket = buckets.setdefault(key, ModelUsage(model=model_name, tokens=TokenTotals.zero(), estimated_cost=CostEstimate()))
            bucket.add(usage.tokens, message_count=usage.message_count)
            if usage.estimated_cost is not None:
                bucket.estimated_cost.add(usage.estimated_cost)
            if usage.attribution_status is not None:
                attribution_statuses[key].add(usage.attribution_status)
            if usage.pricing_model is not None:
                pricing_models[key].add(usage.pricing_model)
            fallback_flags[key] = fallback_flags[key] or usage.is_fallback_model
            sessions_per_model[key].add(record.anon_session_id)

    items: list[dict[str, object]] = []
    for (provider, model), usage in buckets.items():
        total_tokens = usage.tokens.total or 0
        priced_tokens = usage.tokens.total if usage.estimated_cost and usage.estimated_cost.total_cost > 0 else 0
        statuses = attribution_statuses[(provider, model)]
        attribution_status = "fallback" if "fallback" in statuses or fallback_flags[(provider, model)] else "exact" if statuses else None
        resolved_pricing_models = sorted(pricing_models[(provider, model)])
        items.append(
            {
                "provider": provider,
                "model": model,
                "session_count": len(sessions_per_model[(provider, model)]),
                "message_count": usage.message_count,
                "token_totals": usage.tokens.to_dict(),
                "estimated_cost": usage.estimated_cost.to_dict() if usage.estimated_cost is not None else None,
                "priced_token_coverage": round((priced_tokens or 0) / total_tokens, 4) if total_tokens else 0.0,
                "attribution_status": attribution_status,
                "pricing_model": resolved_pricing_models[0] if len(resolved_pricing_models) == 1 else None,
                "is_fallback_model": fallback_flags[(provider, model)],
            }
        )

    items.sort(key=lambda item: (-((item["estimated_cost"] or {}).get("total_cost", 0) if item.get("estimated_cost") else 0), -(item["token_totals"]["total"] or 0), item["provider"], item["model"]))
    return items


def aggregate_daily(records: list[SessionRecord]) -> list[DailyUsageRecord]:
    buckets: dict[date, DailyUsageRecord] = {}
    for record in records:
        timestamp = record.updated_at or record.started_at
        if timestamp is None:
            continue
        day = timestamp.date()
        bucket = buckets.setdefault(day, DailyUsageRecord(date=day))
        bucket.providers.add(record.provider)
        bucket.models.update(record.models)
        bucket.token_totals.add(record.token_totals)
        bucket.session_count += 1
        bucket.total_tokens += record.token_totals.total or 0
        if record.estimated_cost is not None:
            bucket.estimated_cost.add(record.estimated_cost)
        if record.pricing_status in {"priced", "partial"}:
            priced_tokens = sum((usage.tokens.total or 0) for usage in record.model_usage.values() if usage.pricing_status == "priced")
            bucket.priced_tokens += priced_tokens

    return [buckets[key] for key in sorted(buckets)]
