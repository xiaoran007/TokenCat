from __future__ import annotations

from collections import defaultdict

from tokencat.core.models import ModelUsage, ProviderName, SessionRecord, TokenTotals


def aggregate_summary(records: list[SessionRecord]) -> dict[str, object]:
    totals = TokenTotals.zero()
    provider_totals: dict[str, dict[str, object]] = {}
    overall_models: set[str] = set()

    by_provider: dict[ProviderName, list[SessionRecord]] = defaultdict(list)
    for record in records:
        by_provider[record.provider].append(record)
        totals.add(record.token_totals)
        overall_models.update(record.models)

    for provider, provider_records in sorted(by_provider.items(), key=lambda item: item[0].value):
        provider_tokens = TokenTotals.zero()
        provider_models: set[str] = set()
        for record in provider_records:
            provider_tokens.add(record.token_totals)
            provider_models.update(record.models)
        provider_totals[provider.value] = {
            "session_count": len(provider_records),
            "model_count": len(provider_models),
            "token_totals": provider_tokens.to_dict(),
        }

    return {
        "session_count": len(records),
        "model_count": len(overall_models),
        "token_totals": totals.to_dict(),
        "providers": provider_totals,
    }


def aggregate_models(records: list[SessionRecord]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str], ModelUsage] = {}
    sessions_per_model: dict[tuple[str, str], set[str]] = defaultdict(set)

    for record in records:
        for model_name, usage in record.model_usage.items():
            key = (record.provider.value, model_name)
            bucket = buckets.setdefault(key, ModelUsage(model=model_name, tokens=TokenTotals.zero()))
            bucket.add(usage.tokens, message_count=usage.message_count)
            sessions_per_model[key].add(record.anon_session_id)

    items: list[dict[str, object]] = []
    for (provider, model), usage in buckets.items():
        items.append(
            {
                "provider": provider,
                "model": model,
                "session_count": len(sessions_per_model[(provider, model)]),
                "message_count": usage.message_count,
                "token_totals": usage.tokens.to_dict(),
            }
        )

    items.sort(key=lambda item: (-(item["token_totals"]["total"] or 0), item["provider"], item["model"]))
    return items
