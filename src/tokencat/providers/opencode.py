from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tokencat.core.models import (
    ModelUsage,
    ProviderName,
    ProviderStatus,
    ProviderSupportLevel,
    ScanFilters,
    SessionRecord,
    TokenTotals,
    UsageSlice,
)
from tokencat.core.paths import opencode_data_dir, opencode_message_roots, opencode_session_roots
from tokencat.core.privacy import anonymize_session_id
from tokencat.providers.base import ProviderAdapter


class OpenCodeAdapter(ProviderAdapter):
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or Path.home()
        self.data_dir = opencode_data_dir(self.home)
        self.config_dir = self.home / ".config" / "opencode"
        self.config_path = self.config_dir / "opencode.json"
        self.instructions_path = self.config_dir / "AGENTS.md"
        self.db_path = self.data_dir / "opencode.db"
        self.message_roots = opencode_message_roots(self.home)
        self.session_roots = opencode_session_roots(self.home)

    def detect(self) -> ProviderStatus:
        found_paths: list[Path] = []
        reasons: list[str] = []
        warnings: list[str] = []

        for path in (self.config_path, self.instructions_path, self.db_path):
            if path.exists():
                found_paths.append(path)

        session_files = self._session_paths()
        message_paths = self._message_paths()
        if session_files:
            found_paths.extend(path.parent for path in session_files[:3])
        if message_paths:
            found_paths.extend(path.parent for path in message_paths[:3])

        sessions = self.scan(ScanFilters())
        has_tokens = any((record.token_totals.total or record.token_totals.known_total()) > 0 for record in sessions)

        if has_tokens:
            reasons.append("Detected OpenCode local message stores with token usage counters.")
            return ProviderStatus(
                provider=ProviderName.OPENCODE,
                status=ProviderSupportLevel.SUPPORTED,
                found_paths=_dedupe_paths(found_paths),
                reasons=reasons,
                warnings=warnings,
            )

        if sessions:
            reasons.append("Detected OpenCode local session metadata, but no usable token counters were found.")
            return ProviderStatus(
                provider=ProviderName.OPENCODE,
                status=ProviderSupportLevel.PARTIAL,
                found_paths=_dedupe_paths(found_paths),
                reasons=reasons,
                warnings=warnings,
            )

        if message_paths or session_files:
            reasons.append("Detected OpenCode local storage, but no complete assistant usage records were available to scan.")
            return ProviderStatus(
                provider=ProviderName.OPENCODE,
                status=ProviderSupportLevel.PARTIAL,
                found_paths=_dedupe_paths(found_paths),
                reasons=reasons,
                warnings=warnings,
            )

        if self.db_path.exists():
            reasons.append("Detected OpenCode's SQLite store, but TokenCat currently reads the local JSON message/session stores only.")
            warnings.append("OpenCode DB-backed telemetry is not yet parsed by TokenCat.")
            return ProviderStatus(
                provider=ProviderName.OPENCODE,
                status=ProviderSupportLevel.PARTIAL,
                found_paths=_dedupe_paths(found_paths),
                reasons=reasons,
                warnings=warnings,
            )

        if found_paths:
            reasons.append("Potential OpenCode install/config files were detected, but no scannable local telemetry store was found.")
            return ProviderStatus(
                provider=ProviderName.OPENCODE,
                status=ProviderSupportLevel.PARTIAL,
                found_paths=_dedupe_paths(found_paths),
                reasons=reasons,
                warnings=warnings,
            )

        return ProviderStatus(
            provider=ProviderName.OPENCODE,
            status=ProviderSupportLevel.NOT_FOUND,
            reasons=["No OpenCode local telemetry source was found."],
        )

    def scan(self, filters: ScanFilters) -> list[SessionRecord]:
        records: dict[str, SessionRecord] = {}
        for session_path in self._session_paths():
            payload = _load_json(session_path)
            if payload is None:
                continue
            session_id = _session_id_from_payload(payload) or session_path.stem
            if session_id is None:
                continue
            record = records.setdefault(session_id, self._new_record(session_id))
            _apply_session_metadata(record, payload, session_path)

        for message_path in self._message_paths():
            payload = _load_json(message_path)
            if payload is None:
                continue
            session_id = _session_id_from_payload(payload) or _session_id_from_message_path(message_path)
            if session_id is None:
                continue
            record = records.setdefault(session_id, self._new_record(session_id))
            _apply_message(record, payload, message_path)

        return [record for record in records.values() if record.updated_at is not None or record.model_usage or record.source_refs]

    def _session_paths(self) -> list[Path]:
        paths: list[Path] = []
        for root in self.session_roots:
            if not root.exists():
                continue
            paths.extend(path for path in root.rglob("*.json") if path.is_file())
        return sorted(paths)

    def _message_paths(self) -> list[Path]:
        paths: list[Path] = []
        for root in self.message_roots:
            if not root.exists():
                continue
            paths.extend(path for path in root.rglob("*.json") if path.is_file())
        return sorted(paths)

    def _new_record(self, session_id: str) -> SessionRecord:
        return SessionRecord(
            provider=ProviderName.OPENCODE,
            provider_session_id=session_id,
            anon_session_id=anonymize_session_id(ProviderName.OPENCODE, session_id),
            started_at=None,
            updated_at=None,
            token_totals=TokenTotals.zero(),
            metadata={"source": "opencode_local_storage"},
        )


def _apply_session_metadata(record: SessionRecord, payload: dict[str, object], path: Path) -> None:
    record.source_refs = _append_path(record.source_refs, path)
    record.started_at = _pick_earliest(record.started_at, _parse_nested_timestamp(payload, "created"))
    record.updated_at = _pick_latest(record.updated_at, _parse_nested_timestamp(payload, "updated"))
    record.title = record.title or _first_string(payload, "title", "name")
    record.cwd = record.cwd or _first_string(payload, "cwd", "directory")
    project_id = _first_string(payload, "projectID", "projectId")
    if project_id is not None:
        record.metadata.setdefault("project_id", project_id)


def _apply_message(record: SessionRecord, payload: dict[str, object], path: Path) -> None:
    record.source_refs = _append_path(record.source_refs, path)
    message_time = _parse_nested_timestamp(payload, "created") or _parse_timestamp(payload.get("createdAt"))
    record.started_at = _pick_earliest(record.started_at, message_time)
    record.updated_at = _pick_latest(record.updated_at, message_time)

    tokens, cache_write_tokens = _token_totals_from_payload(payload)
    if tokens is None:
        return

    model_name = _normalized_model_name(payload)
    record.token_totals.add(tokens)
    request_count = int(record.metadata.get("request_count", 0) or 0) + 1
    record.metadata["request_count"] = request_count
    if cache_write_tokens:
        record.metadata["cache_write_tokens"] = int(record.metadata.get("cache_write_tokens", 0) or 0) + cache_write_tokens

    attribution_status = "exact" if model_name is not None else None
    if message_time is not None:
        record.usage_slices.append(
            UsageSlice(
                timestamp=message_time,
                model=model_name,
                tokens=tokens,
                message_count=1,
                attribution_status=attribution_status,
            )
        )

    if model_name is None:
        if (record.token_totals.total or record.token_totals.known_total()) > 0:
            record.attribution_status = "partial" if record.model_usage else "unattributed"
        return

    usage = record.model_usage.setdefault(
        model_name,
        ModelUsage(model=model_name, tokens=TokenTotals.zero(), attribution_status="exact"),
    )
    usage.add(tokens, message_count=1)
    usage.attribution_status = "exact"
    record.attribution_status = "exact" if not any(slice_record.model is None for slice_record in record.usage_slices) else "partial"


def _load_json(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _session_id_from_payload(payload: dict[str, object]) -> str | None:
    return _first_string(payload, "sessionID", "sessionId", "session_id", "id")


def _session_id_from_message_path(path: Path) -> str | None:
    parent_name = path.parent.name.strip()
    return parent_name or None


def _first_string(payload: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def _parse_nested_timestamp(payload: dict[str, object], leaf_key: str) -> datetime | None:
    time_payload = payload.get("time")
    if isinstance(time_payload, dict):
        nested = time_payload.get(leaf_key)
        parsed = _parse_timestamp(nested)
        if parsed is not None:
            return parsed
    direct_keys = {
        "created": ("createdAt", "created_at"),
        "updated": ("updatedAt", "updated_at"),
    }
    for key in direct_keys.get(leaf_key, ()):
        parsed = _parse_timestamp(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def _token_totals_from_payload(payload: dict[str, object]) -> tuple[TokenTotals | None, int]:
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return None, 0
        tokens = usage

    input_tokens = _safe_int(tokens.get("input")) or _safe_int(tokens.get("inputTokens")) or 0
    output_tokens = _safe_int(tokens.get("output")) or _safe_int(tokens.get("outputTokens")) or 0
    reasoning_tokens = _safe_int(tokens.get("reasoning")) or _safe_int(tokens.get("reasoningTokens")) or 0
    cached_tokens = _safe_int(tokens.get("cached")) or _safe_int(tokens.get("cachedTokens")) or 0
    cache_write_tokens = 0
    cache_payload = tokens.get("cache")
    if isinstance(cache_payload, dict):
        cached_tokens = _safe_int(cache_payload.get("read")) or cached_tokens
        cache_write_tokens = _safe_int(cache_payload.get("write")) or 0

    total_tokens = _safe_int(tokens.get("total"))
    if total_tokens is None:
        total_tokens = input_tokens + output_tokens + cached_tokens + reasoning_tokens

    if total_tokens == 0 and input_tokens == 0 and output_tokens == 0 and cached_tokens == 0 and reasoning_tokens == 0:
        return None, cache_write_tokens

    return (
        TokenTotals(
            input=input_tokens,
            output=output_tokens,
            cached=cached_tokens,
            reasoning=reasoning_tokens,
            total=total_tokens,
        ),
        cache_write_tokens,
    )


def _normalized_model_name(payload: dict[str, object]) -> str | None:
    model_id = _first_string(payload, "modelID", "modelId", "model")
    provider_id = _first_string(payload, "providerID", "providerId", "provider")
    if model_id is None:
        return None
    if "/" in model_id or provider_id is None:
        return model_id
    return f"{provider_id}/{model_id}"


def _safe_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=UTC).astimezone()
    if isinstance(value, str):
        normalized = value.strip().replace("Z", "+00:00")
        if not normalized:
            return None
        try:
            return datetime.fromisoformat(normalized).astimezone()
        except ValueError:
            return None
    return None


def _pick_latest(current: datetime | None, candidate: datetime | None) -> datetime | None:
    if current is None:
        return candidate
    if candidate is None:
        return current
    return max(current, candidate)


def _pick_earliest(current: datetime | None, candidate: datetime | None) -> datetime | None:
    if current is None:
        return candidate
    if candidate is None:
        return current
    return min(current, candidate)


def _append_path(paths: list[Path], path: Path) -> list[Path]:
    if path not in paths:
        return [*paths, path]
    return paths


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            deduped.append(path)
            seen.add(path)
    return deduped
