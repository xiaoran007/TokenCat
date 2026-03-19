from __future__ import annotations

from tokencat.core.models import ModelUsage, ScanFilters, SessionRecord, TokenTotals, UsageSlice
from tokencat.core.time import matches_time_window


def apply_filters(records: list[SessionRecord], filters: ScanFilters) -> list[SessionRecord]:
    filtered: list[SessionRecord] = []
    for record in records:
        if filters.providers and record.provider not in filters.providers:
            continue

        projected = _project_record_to_window(record, filters.since, filters.until)
        if projected is None:
            continue
        if filters.model and filters.model not in projected.model_usage:
            continue
        filtered.append(projected)

    filtered.sort(key=lambda record: record.updated_at or record.started_at, reverse=True)
    if filters.limit is not None:
        return filtered[: filters.limit]
    return filtered


def _project_record_to_window(record: SessionRecord, since, until) -> SessionRecord | None:
    if since is None and until is None:
        return record

    if record.usage_slices:
        included_slices = [slice_record for slice_record in record.usage_slices if _slice_in_window(slice_record, since, until)]
        if not included_slices:
            return None
        return _project_precise_record(record, included_slices)

    if not matches_time_window(record.started_at, record.updated_at, since, until):
        return None
    return record


def _slice_in_window(slice_record: UsageSlice, since, until) -> bool:
    if since is not None and slice_record.timestamp < since:
        return False
    if until is not None and slice_record.timestamp > until:
        return False
    return True


def _project_precise_record(record: SessionRecord, included_slices: list[UsageSlice]) -> SessionRecord:
    projected = SessionRecord(
        provider=record.provider,
        provider_session_id=record.provider_session_id,
        anon_session_id=record.anon_session_id,
        started_at=min(slice_record.timestamp for slice_record in included_slices),
        updated_at=max(slice_record.timestamp for slice_record in included_slices),
        token_totals=TokenTotals.zero(),
        source_refs=list(record.source_refs),
        model_usage={},
        usage_slices=list(included_slices),
        primary_model_override=record.primary_model_override,
        title=record.title,
        cwd=record.cwd,
        metadata=dict(record.metadata),
    )

    saw_unattributed_tokens = False

    for slice_record in included_slices:
        projected.token_totals.add(slice_record.tokens)
        if slice_record.model is None:
            saw_unattributed_tokens = saw_unattributed_tokens or (slice_record.tokens.total or slice_record.tokens.known_total()) > 0
            continue

        usage = projected.model_usage.setdefault(
            slice_record.model,
            ModelUsage(model=slice_record.model, tokens=TokenTotals.zero()),
        )
        usage.add(slice_record.tokens, message_count=slice_record.message_count)
        usage.attribution_status = _pick_attribution_status(usage.attribution_status, slice_record.attribution_status)
        usage.is_fallback_model = usage.is_fallback_model or slice_record.is_fallback_model

    if projected.primary_model_override not in projected.model_usage:
        projected.primary_model_override = None

    request_count = sum(slice_record.message_count for slice_record in included_slices)
    if "request_count" in projected.metadata:
        projected.metadata["request_count"] = request_count

    if projected.model_usage:
        projected.is_fallback_model = any(usage.is_fallback_model for usage in projected.model_usage.values())
        if saw_unattributed_tokens:
            projected.attribution_status = "partial"
        elif projected.is_fallback_model:
            projected.attribution_status = "fallback"
        else:
            projected.attribution_status = "exact"
    elif (projected.token_totals.total or projected.token_totals.known_total()) > 0:
        projected.attribution_status = "unattributed"

    return projected


def _pick_attribution_status(current: str | None, incoming: str | None) -> str | None:
    if current == "exact" or incoming is None:
        return current
    if incoming == "exact" or current is None:
        return incoming
    if incoming == "fallback":
        return "fallback"
    return current or incoming
