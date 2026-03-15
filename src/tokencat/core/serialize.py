from __future__ import annotations

from datetime import datetime
from pathlib import Path

from tokencat.core.models import ProviderStatus, ScanFilters, SessionRecord


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
