from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
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
from tokencat.core.privacy import anonymize_session_id
from tokencat.core.time import parse_iso_datetime, parse_unix_timestamp
from tokencat.providers.base import ProviderAdapter

SESSION_ID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
LEGACY_FALLBACK_MODEL = "gpt-5"


@dataclass(slots=True)
class RawUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    tool_tokens: int
    total_tokens: int


class CodexAdapter(ProviderAdapter):
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or Path.home()
        self.codex_dir = self.home / ".codex"
        self.sessions_dir = self.codex_dir / "sessions"
        self.archived_dir = self.codex_dir / "archived_sessions"
        self.session_index_path = self.codex_dir / "session_index.jsonl"

    def detect(self) -> ProviderStatus:
        found_paths: list[Path] = []
        reasons: list[str] = []
        warnings: list[str] = []
        status = ProviderSupportLevel.NOT_FOUND

        session_paths = self._jsonl_session_paths()
        has_active_sessions = any(path.is_relative_to(self.sessions_dir) for path in session_paths if self.sessions_dir.exists())
        has_archived_sessions = any(path.is_relative_to(self.archived_dir) for path in session_paths if self.archived_dir.exists())
        state_paths = self._state_db_paths()

        if has_active_sessions:
            found_paths.append(self.sessions_dir)
            reasons.append("Detected active Codex session JSONL files under ~/.codex/sessions.")
        if has_archived_sessions:
            found_paths.append(self.archived_dir)
            reasons.append("Detected archived Codex session JSONL files under ~/.codex/archived_sessions.")
        if self.session_index_path.exists():
            found_paths.append(self.session_index_path)
        found_paths.extend(state_paths)

        if has_active_sessions or has_archived_sessions:
            status = ProviderSupportLevel.SUPPORTED
        elif state_paths:
            status = ProviderSupportLevel.PARTIAL
            reasons.append("Only SQLite fallback telemetry was found; per-model Codex analytics may be incomplete.")
            warnings.append("Codex model attribution is degraded when only state_*.sqlite is available.")

        if status is ProviderSupportLevel.NOT_FOUND:
            reasons.append("No Codex local telemetry sources found under ~/.codex.")

        return ProviderStatus(
            provider=ProviderName.CODEX,
            status=status,
            found_paths=found_paths,
            reasons=reasons,
            warnings=warnings,
        )

    def scan(self, filters: ScanFilters) -> list[SessionRecord]:
        title_index = self._load_session_index()
        sqlite_rows = self._load_state_rows()
        sessions: dict[str, SessionRecord] = {}

        for path in self._jsonl_session_paths():
            session = self._parse_session_file(path, title_index)
            if session is None:
                continue
            existing = sessions.get(session.provider_session_id)
            if existing is None:
                sessions[session.provider_session_id] = session
            else:
                sessions[session.provider_session_id] = _prefer_richer_record(existing, session)

        for session_id, row in sqlite_rows.items():
            record = sessions.get(session_id)
            if record is None:
                record = SessionRecord(
                    provider=ProviderName.CODEX,
                    provider_session_id=session_id,
                    anon_session_id=anonymize_session_id(ProviderName.CODEX, session_id),
                    started_at=row["created_at"],
                    updated_at=row["updated_at"],
                    token_totals=TokenTotals(total=row["tokens_used"]),
                    title=title_index.get(session_id) or row["title"],
                    cwd=row["cwd"],
                    metadata={
                        "source": row["source"],
                        "model_provider": row["model_provider"],
                        "cli_version": row["cli_version"],
                    },
                    attribution_status="unattributed",
                )
                sessions[session_id] = record
                continue

            record.started_at = _pick_earliest(record.started_at, row["created_at"])
            record.updated_at = _pick_latest(record.updated_at, row["updated_at"])
            if record.title is None:
                record.title = title_index.get(session_id) or row["title"]
            if record.cwd is None:
                record.cwd = row["cwd"]
            if (record.token_totals.total is None or record.token_totals.total == 0) and row["tokens_used"] is not None:
                record.token_totals.total = row["tokens_used"]
            for key in ("source", "model_provider", "cli_version"):
                if key not in record.metadata and row[key] is not None:
                    record.metadata[key] = row[key]
            if not record.model_usage and (record.token_totals.total or 0) > 0:
                record.attribution_status = "unattributed"

        return list(sessions.values())

    def _parse_session_file(self, path: Path, title_index: dict[str, str]) -> SessionRecord | None:
        session_id = _session_id_from_name(path.name)
        record: SessionRecord | None = None
        current_model: str | None = None
        current_model_is_fallback = False
        first_seen = None
        last_seen = None
        previous_totals: RawUsage | None = None

        try:
            handle = path.open("r", encoding="utf-8")
        except OSError:
            return None

        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue

                timestamp = parse_iso_datetime(payload.get("timestamp"))
                first_seen = _pick_earliest(first_seen, timestamp)
                last_seen = _pick_latest(last_seen, timestamp)

                event_type = payload.get("type")
                event_payload = payload.get("payload")

                if event_type == "session_meta" and isinstance(event_payload, dict):
                    session_id = event_payload.get("id") or session_id
                    if session_id is None:
                        continue
                    record = record or self._new_record(session_id)
                    record.started_at = _pick_earliest(record.started_at, parse_iso_datetime(event_payload.get("timestamp")))
                    record.cwd = record.cwd or _as_non_empty_string(event_payload.get("cwd"))
                    record.title = record.title or title_index.get(session_id)
                    for key in ("source", "model_provider", "cli_version", "originator"):
                        value = event_payload.get(key)
                        if value is not None:
                            record.metadata[key] = value
                    continue

                if event_type == "turn_context" and isinstance(event_payload, dict):
                    session_id = session_id or _session_id_from_name(path.name)
                    if session_id is None:
                        continue
                    record = record or self._new_record(session_id)
                    model = _extract_model(event_payload)
                    if model is not None:
                        current_model = model
                        current_model_is_fallback = False
                    if record.cwd is None:
                        record.cwd = _as_non_empty_string(event_payload.get("cwd"))
                    continue

                if event_type != "event_msg" or not isinstance(event_payload, dict) or event_payload.get("type") != "token_count":
                    continue

                session_id = session_id or _session_id_from_name(path.name)
                if session_id is None:
                    continue
                record = record or self._new_record(session_id)

                info = event_payload.get("info")
                if not isinstance(info, dict):
                    continue

                last_usage = _normalize_raw_usage(info.get("last_token_usage"))
                total_usage = _normalize_raw_usage(info.get("total_token_usage"))
                raw_usage = last_usage
                if raw_usage is None and total_usage is not None:
                    raw_usage = _subtract_raw_usage(total_usage, previous_totals)
                if total_usage is not None:
                    previous_totals = total_usage
                if raw_usage is None:
                    continue

                tokens = _convert_to_token_totals(raw_usage)
                if tokens.known_total() == 0 and (tokens.total or 0) == 0:
                    continue

                model = _extract_model({"info": info, **event_payload}) or current_model
                is_fallback_model = False
                if model is None:
                    model = LEGACY_FALLBACK_MODEL
                    is_fallback_model = True
                    current_model_is_fallback = True
                elif _extract_model({"info": info, **event_payload}) is None and current_model_is_fallback:
                    is_fallback_model = True
                else:
                    current_model_is_fallback = False
                current_model = model

                record.token_totals.add(tokens)
                usage = record.model_usage.setdefault(model, ModelUsage(model=model, tokens=TokenTotals.zero()))
                usage.add(tokens, message_count=1)
                usage.is_fallback_model = usage.is_fallback_model or is_fallback_model
                usage.attribution_status = "fallback" if usage.is_fallback_model else "exact"
                if timestamp is not None:
                    record.usage_slices.append(
                        UsageSlice(
                            timestamp=timestamp,
                            model=model,
                            tokens=tokens,
                            message_count=1,
                            attribution_status="fallback" if is_fallback_model else "exact",
                            is_fallback_model=is_fallback_model,
                        )
                    )

        if record is None and session_id is not None:
            record = self._new_record(session_id)
        if record is None:
            return None

        record.started_at = _pick_earliest(record.started_at, first_seen)
        record.updated_at = _pick_latest(record.updated_at, last_seen)
        record.title = record.title or title_index.get(record.provider_session_id)
        record.source_refs.append(path)
        if record.model_usage:
            record.attribution_status = "fallback" if any(usage.is_fallback_model for usage in record.model_usage.values()) else "exact"
            record.is_fallback_model = any(usage.is_fallback_model for usage in record.model_usage.values())
        elif (record.token_totals.total or 0) > 0:
            record.attribution_status = "unattributed"
        return record

    def _new_record(self, session_id: str) -> SessionRecord:
        return SessionRecord(
            provider=ProviderName.CODEX,
            provider_session_id=session_id,
            anon_session_id=anonymize_session_id(ProviderName.CODEX, session_id),
            started_at=None,
            updated_at=None,
            token_totals=TokenTotals.zero(),
        )

    def _jsonl_session_paths(self) -> list[Path]:
        paths: list[Path] = []
        if self.sessions_dir.exists():
            paths.extend(sorted(self.sessions_dir.rglob("*.jsonl")))
        if self.archived_dir.exists():
            paths.extend(sorted(self.archived_dir.glob("*.jsonl")))
        return paths

    def _load_session_index(self) -> dict[str, str]:
        titles: dict[str, str] = {}
        if not self.session_index_path.exists():
            return titles

        try:
            handle = self.session_index_path.open("r", encoding="utf-8")
        except OSError:
            return titles

        with handle:
            for line in handle:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session_id = payload.get("id")
                title = payload.get("thread_name")
                if session_id and title:
                    titles[session_id] = title
        return titles

    def _load_state_rows(self) -> dict[str, dict[str, object]]:
        rows: dict[str, dict[str, object]] = {}
        query = (
            "select id, created_at, updated_at, tokens_used, cwd, title, source, model_provider, cli_version "
            "from threads"
        )
        for db_path in self._state_db_paths():
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            except sqlite3.Error:
                continue
            with conn:
                try:
                    result = conn.execute(query).fetchall()
                except sqlite3.Error:
                    continue
            for session_id, created_at, updated_at, tokens_used, cwd, title, source, model_provider, cli_version in result:
                current = rows.get(session_id)
                row = {
                    "created_at": parse_unix_timestamp(created_at),
                    "updated_at": parse_unix_timestamp(updated_at),
                    "tokens_used": tokens_used,
                    "cwd": cwd,
                    "title": title,
                    "source": source,
                    "model_provider": model_provider,
                    "cli_version": cli_version,
                }
                if current is None or (row["updated_at"] or row["created_at"]) > (current["updated_at"] or current["created_at"]):
                    rows[session_id] = row
        return rows

    def _state_db_paths(self) -> list[Path]:
        return sorted(self.codex_dir.glob("state_*.sqlite"))


def _session_id_from_name(name: str) -> str | None:
    match = SESSION_ID_RE.search(name)
    return match.group(1) if match else None


def _pick_latest(current, candidate):
    if current is None:
        return candidate
    if candidate is None:
        return current
    return max(current, candidate)


def _pick_earliest(current, candidate):
    if current is None:
        return candidate
    if candidate is None:
        return current
    return min(current, candidate)


def _as_non_empty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _ensure_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _normalize_raw_usage(value: object) -> RawUsage | None:
    if not isinstance(value, dict):
        return None
    input_tokens = _ensure_int(value.get("input_tokens"))
    cached_input_tokens = _ensure_int(value.get("cached_input_tokens") or value.get("cache_read_input_tokens"))
    output_tokens = _ensure_int(value.get("output_tokens"))
    reasoning_output_tokens = _ensure_int(value.get("reasoning_output_tokens"))
    tool_tokens = _ensure_int(value.get("tool_tokens"))
    total_tokens = _ensure_int(value.get("total_tokens"))
    normalized_total = total_tokens if total_tokens > 0 else input_tokens + output_tokens
    return RawUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
        tool_tokens=tool_tokens,
        total_tokens=normalized_total,
    )


def _subtract_raw_usage(current: RawUsage, previous: RawUsage | None) -> RawUsage:
    return RawUsage(
        input_tokens=max(current.input_tokens - (previous.input_tokens if previous else 0), 0),
        cached_input_tokens=max(current.cached_input_tokens - (previous.cached_input_tokens if previous else 0), 0),
        output_tokens=max(current.output_tokens - (previous.output_tokens if previous else 0), 0),
        reasoning_output_tokens=max(
            current.reasoning_output_tokens - (previous.reasoning_output_tokens if previous else 0),
            0,
        ),
        tool_tokens=max(current.tool_tokens - (previous.tool_tokens if previous else 0), 0),
        total_tokens=max(current.total_tokens - (previous.total_tokens if previous else 0), 0),
    )


def _convert_to_token_totals(raw_usage: RawUsage) -> TokenTotals:
    cached_tokens = min(raw_usage.cached_input_tokens, raw_usage.input_tokens)
    total_tokens = raw_usage.total_tokens if raw_usage.total_tokens > 0 else raw_usage.input_tokens + raw_usage.output_tokens
    return TokenTotals(
        input=raw_usage.input_tokens,
        output=raw_usage.output_tokens,
        cached=cached_tokens,
        reasoning=raw_usage.reasoning_output_tokens,
        tool=raw_usage.tool_tokens,
        total=total_tokens,
    )


def _extract_model(value: object) -> str | None:
    if not isinstance(value, dict):
        return None

    info = value.get("info")
    if isinstance(info, dict):
        for candidate in (info.get("model"), info.get("model_name")):
            model = _as_non_empty_string(candidate)
            if model is not None:
                return model
        metadata = info.get("metadata")
        if isinstance(metadata, dict):
            model = _as_non_empty_string(metadata.get("model"))
            if model is not None:
                return model

    for candidate in (value.get("model"), value.get("model_name")):
        model = _as_non_empty_string(candidate)
        if model is not None:
            return model

    metadata = value.get("metadata")
    if isinstance(metadata, dict):
        model = _as_non_empty_string(metadata.get("model"))
        if model is not None:
            return model

    return None


def _record_score(record: SessionRecord) -> tuple[int, int, int]:
    return (
        len(record.model_usage),
        sum(usage.message_count for usage in record.model_usage.values()),
        record.token_totals.total or 0,
    )


def _prefer_richer_record(left: SessionRecord, right: SessionRecord) -> SessionRecord:
    winner = left if _record_score(left) >= _record_score(right) else right
    other = right if winner is left else left

    winner.started_at = _pick_earliest(winner.started_at, other.started_at)
    winner.updated_at = _pick_latest(winner.updated_at, other.updated_at)
    if winner.title is None:
        winner.title = other.title
    if winner.cwd is None:
        winner.cwd = other.cwd
    if (winner.token_totals.total is None or winner.token_totals.total == 0) and other.token_totals.total:
        winner.token_totals.total = other.token_totals.total
    if winner.attribution_status is None:
        winner.attribution_status = other.attribution_status
    winner.is_fallback_model = winner.is_fallback_model or other.is_fallback_model
    for key, value in other.metadata.items():
        winner.metadata.setdefault(key, value)
    for source_ref in other.source_refs:
        if source_ref not in winner.source_refs:
            winner.source_refs.append(source_ref)
    if not winner.usage_slices and other.usage_slices:
        winner.usage_slices = list(other.usage_slices)
    elif other.usage_slices:
        existing_keys = {
            (
                slice_record.timestamp,
                slice_record.model,
                slice_record.tokens.to_dict()["total"],
                slice_record.message_count,
            )
            for slice_record in winner.usage_slices
        }
        for slice_record in other.usage_slices:
            key = (
                slice_record.timestamp,
                slice_record.model,
                slice_record.tokens.to_dict()["total"],
                slice_record.message_count,
            )
            if key not in existing_keys:
                winner.usage_slices.append(slice_record)
                existing_keys.add(key)
        winner.usage_slices.sort(key=lambda item: item.timestamp)
    return winner
