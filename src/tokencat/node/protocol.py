from __future__ import annotations

from tokencat.core.models import ProviderName, ScanFilters
from tokencat.core.serialize import serialize_filters
from tokencat.core.time import parse_datetime_value


def snapshot_request_from_filters(
    filters: ScanFilters,
    *,
    include_paths: bool = False,
    include_titles: bool = False,
) -> dict[str, object]:
    payload = serialize_filters(filters)
    payload["include_paths"] = include_paths
    payload["include_titles"] = include_titles
    return payload


def filters_from_snapshot_request(payload: dict[str, object]) -> ScanFilters:
    providers_payload = payload.get("providers")
    providers = None
    if isinstance(providers_payload, list):
        providers = {ProviderName(str(item)) for item in providers_payload if item}

    since = _parse_datetime_field(payload.get("since"), bound="since")
    until = _parse_datetime_field(payload.get("until"), bound="until")
    limit = payload.get("limit")
    model = payload.get("model")

    return ScanFilters(
        providers=providers,
        since=since,
        until=until,
        limit=int(limit) if limit is not None else None,
        model=str(model) if model else None,
        show_title=bool(payload.get("show_title")),
        show_path=bool(payload.get("show_path")),
    )


def _parse_datetime_field(value: object, *, bound: str):
    if value is None:
        return None
    return parse_datetime_value(str(value), bound=bound)
