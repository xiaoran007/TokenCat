from __future__ import annotations

from tokencat.core.models import ScanFilters, SessionRecord
from tokencat.core.time import matches_time_window


def apply_filters(records: list[SessionRecord], filters: ScanFilters) -> list[SessionRecord]:
    filtered: list[SessionRecord] = []
    for record in records:
        if filters.providers and record.provider not in filters.providers:
            continue
        if filters.model and filters.model not in record.model_usage:
            continue
        if not matches_time_window(record.started_at, record.updated_at, filters.since, filters.until):
            continue
        filtered.append(record)

    filtered.sort(key=lambda record: record.updated_at or record.started_at, reverse=True)
    if filters.limit is not None:
        return filtered[: filters.limit]
    return filtered
