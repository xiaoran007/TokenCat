from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from tokencat.core.models import (
    CostEstimate,
    ModelUsage,
    ProviderName,
    ProviderStatus,
    ProviderSupportLevel,
    ScanFilters,
    ScanResult,
    SessionRecord,
    TokenTotals,
    UsageSlice,
)
from tokencat.core.serialize import serialize_datetime, serialize_filters, serialize_status
from tokencat.node.identity import NodeIdentity, apply_node_identity

SNAPSHOT_SCHEMA_VERSION = 1


def build_snapshot_payload(
    *,
    identity: NodeIdentity,
    filters: ScanFilters,
    result: ScanResult,
    include_paths: bool = False,
    include_titles: bool = False,
) -> dict[str, object]:
    apply_node_identity(result.sessions, identity)
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "node": identity.to_dict(),
        "filters": serialize_filters(filters),
        "providers": [serialize_status(status) for status in result.statuses],
        "sessions": [
            _serialize_session_snapshot(record, include_paths=include_paths, include_titles=include_titles)
            for record in result.sessions
        ],
        "warnings": result.warnings,
    }


def scan_result_from_snapshot(payload: dict[str, Any]) -> tuple[NodeIdentity, ScanResult]:
    schema_version = payload.get("schema_version")
    if schema_version != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported snapshot schema version: {schema_version}")

    node_payload = payload.get("node")
    if not isinstance(node_payload, dict):
        raise ValueError("Snapshot is missing node metadata")
    node = NodeIdentity(
        node_id=_required_string(node_payload, "id"),
        name=_required_string(node_payload, "name"),
        version=str(node_payload.get("version") or "unknown"),
        api_version=int(node_payload.get("api_version") or 1),
    )

    statuses = [_deserialize_status(item) for item in _list_of_dicts(payload.get("providers"))]
    sessions = [_deserialize_session_snapshot(item, node) for item in _list_of_dicts(payload.get("sessions"))]
    warnings = [str(item) for item in payload.get("warnings") or []]
    return node, ScanResult(statuses=statuses, sessions=sessions, warnings=warnings)


def _serialize_session_snapshot(record: SessionRecord, *, include_paths: bool, include_titles: bool) -> dict[str, object]:
    data: dict[str, object] = {
        "provider": record.provider.value,
        "provider_session_id": record.provider_session_id if include_paths else None,
        "anon_session_id": record.anon_session_id,
        "node_id": record.node_id,
        "node_name": record.node_name,
        "started_at": serialize_datetime(record.started_at),
        "updated_at": serialize_datetime(record.updated_at),
        "token_totals": record.token_totals.to_dict(),
        "model_usage": {
            model: _serialize_model_usage(usage)
            for model, usage in sorted(record.model_usage.items())
        },
        "usage_slices": [_serialize_usage_slice(slice_record) for slice_record in record.usage_slices],
        "primary_model_override": record.primary_model_override,
        "metadata": _redact_metadata(record.metadata, include_paths=include_paths),
        "estimated_cost": record.estimated_cost.to_dict() if record.estimated_cost is not None else None,
        "attribution_status": record.attribution_status,
        "pricing_status": record.pricing_status,
        "pricing_model": record.pricing_model,
        "pricing_source": record.pricing_source,
        "is_fallback_model": record.is_fallback_model,
    }
    if include_titles:
        data["title"] = record.title
    if include_paths:
        data["cwd"] = record.cwd
        data["source_refs"] = [str(path) for path in record.source_refs]
    return data


def _serialize_model_usage(usage: ModelUsage) -> dict[str, object]:
    return {
        "model": usage.model,
        "tokens": usage.tokens.to_dict(),
        "message_count": usage.message_count,
        "estimated_cost": usage.estimated_cost.to_dict() if usage.estimated_cost is not None else None,
        "attribution_status": usage.attribution_status,
        "pricing_status": usage.pricing_status,
        "pricing_model": usage.pricing_model,
        "pricing_source": usage.pricing_source,
        "is_fallback_model": usage.is_fallback_model,
    }


def _serialize_usage_slice(slice_record: UsageSlice) -> dict[str, object]:
    return {
        "timestamp": serialize_datetime(slice_record.timestamp),
        "model": slice_record.model,
        "tokens": slice_record.tokens.to_dict(),
        "message_count": slice_record.message_count,
        "attribution_status": slice_record.attribution_status,
        "is_fallback_model": slice_record.is_fallback_model,
    }


def _deserialize_session_snapshot(payload: dict[str, Any], node: NodeIdentity) -> SessionRecord:
    provider = ProviderName(_required_string(payload, "provider"))
    anon_session_id = _required_string(payload, "anon_session_id")
    provider_session_id = _string_or_none(payload.get("provider_session_id")) or f"remote:{node.node_id}:{anon_session_id}"
    record = SessionRecord(
        provider=provider,
        provider_session_id=provider_session_id,
        anon_session_id=anon_session_id,
        started_at=_datetime_or_none(payload.get("started_at")),
        updated_at=_datetime_or_none(payload.get("updated_at")),
        token_totals=_deserialize_tokens(payload.get("token_totals")),
        source_refs=[Path(str(path)) for path in payload.get("source_refs") or []],
        model_usage={},
        usage_slices=[],
        primary_model_override=_string_or_none(payload.get("primary_model_override")),
        title=_string_or_none(payload.get("title")),
        cwd=_string_or_none(payload.get("cwd")),
        metadata=_deserialize_metadata(payload.get("metadata")),
        estimated_cost=_deserialize_cost(payload.get("estimated_cost")),
        attribution_status=_string_or_none(payload.get("attribution_status")),
        pricing_status=_string_or_none(payload.get("pricing_status")),
        pricing_model=_string_or_none(payload.get("pricing_model")),
        pricing_source=_string_or_none(payload.get("pricing_source")),
        is_fallback_model=bool(payload.get("is_fallback_model")),
        node_id=_string_or_none(payload.get("node_id")) or node.node_id,
        node_name=_string_or_none(payload.get("node_name")) or node.name,
    )
    record.model_usage = {
        model: _deserialize_model_usage(model_payload, fallback_model=model)
        for model, model_payload in (payload.get("model_usage") or {}).items()
        if isinstance(model_payload, dict)
    }
    record.usage_slices = [
        _deserialize_usage_slice(slice_payload)
        for slice_payload in payload.get("usage_slices") or []
        if isinstance(slice_payload, dict)
    ]
    return record


def _deserialize_model_usage(payload: dict[str, Any], *, fallback_model: str) -> ModelUsage:
    return ModelUsage(
        model=_string_or_none(payload.get("model")) or fallback_model,
        tokens=_deserialize_tokens(payload.get("tokens")),
        message_count=int(payload.get("message_count") or 0),
        estimated_cost=_deserialize_cost(payload.get("estimated_cost")),
        attribution_status=_string_or_none(payload.get("attribution_status")),
        pricing_status=_string_or_none(payload.get("pricing_status")),
        pricing_model=_string_or_none(payload.get("pricing_model")),
        pricing_source=_string_or_none(payload.get("pricing_source")),
        is_fallback_model=bool(payload.get("is_fallback_model")),
    )


def _deserialize_usage_slice(payload: dict[str, Any]) -> UsageSlice:
    timestamp = _datetime_or_none(payload.get("timestamp"))
    if timestamp is None:
        raise ValueError("Usage slice is missing timestamp")
    return UsageSlice(
        timestamp=timestamp,
        model=_string_or_none(payload.get("model")),
        tokens=_deserialize_tokens(payload.get("tokens")),
        message_count=int(payload.get("message_count") or 0),
        attribution_status=_string_or_none(payload.get("attribution_status")),
        is_fallback_model=bool(payload.get("is_fallback_model")),
    )


def _deserialize_status(payload: dict[str, Any]) -> ProviderStatus:
    return ProviderStatus(
        provider=ProviderName(_required_string(payload, "provider")),
        status=ProviderSupportLevel(_required_string(payload, "status")),
        found_paths=[Path(str(path)) for path in payload.get("found_paths") or []],
        ignored_paths=[Path(str(path)) for path in payload.get("ignored_paths") or []],
        reasons=[str(item) for item in payload.get("reasons") or []],
        warnings=[str(item) for item in payload.get("warnings") or []],
    )


def _deserialize_tokens(payload: object) -> TokenTotals:
    data = payload if isinstance(payload, dict) else {}
    return TokenTotals(
        input=_int_or_none(data.get("input")),
        output=_int_or_none(data.get("output")),
        cached=_int_or_none(data.get("cached")),
        reasoning=_int_or_none(data.get("reasoning")),
        tool=_int_or_none(data.get("tool")),
        total=_int_or_none(data.get("total")),
    )


def _deserialize_cost(payload: object) -> CostEstimate | None:
    if not isinstance(payload, dict):
        return None
    return CostEstimate(
        input_cost=float(payload.get("input_cost") or 0.0),
        cached_input_cost=float(payload.get("cached_input_cost") or 0.0),
        output_cost=float(payload.get("output_cost") or 0.0),
        total_cost=float(payload.get("total_cost") or 0.0),
        currency=str(payload.get("currency") or "USD"),
    )


def _deserialize_metadata(payload: object) -> dict[str, str | int | float | None]:
    if not isinstance(payload, dict):
        return {}
    allowed: dict[str, str | int | float | None] = {}
    for key, value in payload.items():
        if isinstance(value, (str, int, float)) or value is None:
            allowed[str(key)] = value
    return allowed


def _redact_metadata(metadata: dict[str, str | int | float | None], *, include_paths: bool) -> dict[str, str | int | float | None]:
    blocked_keys = {"message_preview", "raw_text"}
    if not include_paths:
        blocked_keys.update({"project_hash", "source_root"})
    return {key: value for key, value in metadata.items() if key not in blocked_keys}


def _datetime_or_none(value: object) -> datetime | None:
    text = _string_or_none(value)
    if text is None:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = _string_or_none(payload.get(key))
    if value is None:
        raise ValueError(f"Missing required snapshot field: {key}")
    return value


def _list_of_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
