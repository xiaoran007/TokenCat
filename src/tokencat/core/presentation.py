from __future__ import annotations

from dataclasses import replace
from typing import Any

from tokencat.core.models import DailyModelUsageRecord, DailyUsageRecord, ProviderName, SessionRecord, TokenTotals

FORMAL_PROVIDER_NAMES = {
    ProviderName.CODEX.value: "Codex",
    ProviderName.GEMINI.value: "Gemini CLI",
    ProviderName.COPILOT.value: "GitHub Copilot CLI",
    ProviderName.OPENCODE.value: "OpenCode",
}


def provider_display_name(provider: ProviderName | str) -> str:
    key = provider.value if isinstance(provider, ProviderName) else str(provider)
    return FORMAL_PROVIDER_NAMES.get(key, key)


def is_display_invalid_session(record: SessionRecord) -> bool:
    has_model = _has_usable_model_name(record.primary_model)
    has_model_usage = bool(record.model_usage)
    known_total = _token_total(record.token_totals)
    return (not has_model) and (not has_model_usage) and known_total == 0


def filter_displayable_sessions(records: list[SessionRecord]) -> list[SessionRecord]:
    return [record for record in records if not is_display_invalid_session(record)]


def filter_displayable_model_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if not _is_display_invalid_model_item(item)]


def filter_displayable_daily_records(records: list[DailyUsageRecord]) -> list[DailyUsageRecord]:
    visible: list[DailyUsageRecord] = []
    for record in records:
        models = [model for model in record.models if not _is_display_invalid_daily_model(model)]
        if not models and _token_total(record.token_totals) == 0:
            continue
        visible.append(replace(record, models=models))
    return visible


def _is_display_invalid_daily_model(record: DailyModelUsageRecord) -> bool:
    return (not _has_usable_model_name(record.model)) and _token_total(record.token_totals) == 0


def _is_display_invalid_model_item(item: dict[str, Any]) -> bool:
    model = item.get("model")
    token_totals = item.get("token_totals") or {}
    return (not _has_usable_model_name(model)) and _token_total(token_totals) == 0


def _has_usable_model_name(model: object) -> bool:
    if not isinstance(model, str):
        return False
    value = model.strip()
    return bool(value) and value.lower() != "unknown"


def _token_total(tokens: TokenTotals | dict[str, Any]) -> int:
    if isinstance(tokens, TokenTotals):
        return tokens.total or tokens.known_total()
    total = tokens.get("total")
    if isinstance(total, int):
        return total
    return sum(value for value in tokens.values() if isinstance(value, int))
