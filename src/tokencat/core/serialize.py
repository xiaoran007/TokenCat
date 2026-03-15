from __future__ import annotations

from datetime import datetime
from pathlib import Path

from tokencat.core.models import DailyUsageRecord, PricingCatalog, PricingCoverage, ProviderStatus, ScanFilters, SessionRecord


def serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_filters(filters: ScanFilters) -> dict[str, object]:
    providers = sorted(provider.value for provider in filters.providers) if filters.providers else None
    return {
        "providers": providers,
        "since": serialize_datetime(filters.since),
        "until": serialize_datetime(filters.until),
        "limit": filters.limit,
        "model": filters.model,
        "show_title": filters.show_title,
        "show_path": filters.show_path,
    }


def serialize_status(status: ProviderStatus) -> dict[str, object]:
    return {
        "provider": status.provider.value,
        "status": status.status.value,
        "found_paths": [str(path) for path in status.found_paths],
        "ignored_paths": [str(path) for path in status.ignored_paths],
        "reasons": status.reasons,
        "warnings": status.warnings,
    }


def serialize_session(record: SessionRecord, *, show_title: bool, show_path: bool) -> dict[str, object]:
    data: dict[str, object] = {
        "provider": record.provider.value,
        "anon_session_id": record.anon_session_id,
        "started_at": serialize_datetime(record.started_at),
        "updated_at": serialize_datetime(record.updated_at),
        "models": record.models,
        "primary_model": record.primary_model,
        "token_totals": record.token_totals.to_dict(),
    }
    if record.estimated_cost is not None:
        data["estimated_cost"] = record.estimated_cost.to_dict()
    if record.attribution_status is not None:
        data["attribution_status"] = record.attribution_status
    if record.pricing_status is not None:
        data["pricing_status"] = record.pricing_status
    if record.pricing_model is not None:
        data["pricing_model"] = record.pricing_model
    if record.is_fallback_model:
        data["is_fallback_model"] = True

    if show_title:
        data["title"] = record.title
    if show_path:
        data["provider_session_id"] = record.provider_session_id
        data["cwd"] = record.cwd
        data["source_refs"] = [str(path) for path in record.source_refs]

    if record.metadata:
        blocked_keys = {"message_preview", "raw_text"}
        if not show_path:
            blocked_keys.add("project_hash")
        redacted = {key: value for key, value in record.metadata.items() if key not in blocked_keys}
        if redacted:
            data["metadata"] = redacted

    return data


def serialize_path(path: Path) -> str:
    return str(path.expanduser())


def serialize_pricing_catalog(catalog: PricingCatalog | None) -> dict[str, object] | None:
    if catalog is None:
        return None
    return {
        "source": catalog.source,
        "loaded_at": serialize_datetime(catalog.loaded_at),
        "source_url": catalog.source_url,
        "refreshed_at": catalog.refreshed_at,
        "cache_path": str(catalog.cache_path) if catalog.cache_path else None,
        "model_count": catalog.model_count,
        "entries": [entry.to_dict() for entry in sorted(catalog.entries.values(), key=lambda item: (item.provider.value, item.model))],
    }


def serialize_pricing_coverage(coverage: PricingCoverage | None) -> dict[str, object] | None:
    if coverage is None:
        return None
    return coverage.to_dict()


def serialize_daily_records(records: list[DailyUsageRecord]) -> list[dict[str, object]]:
    return [record.to_dict() for record in records]
