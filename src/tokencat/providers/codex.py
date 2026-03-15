from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from tokencat.core.models import ModelUsage, ProviderName, ProviderStatus, ProviderSupportLevel, ScanFilters, SessionRecord, TokenTotals
from tokencat.core.privacy import anonymize_session_id
from tokencat.core.time import parse_iso_datetime, parse_unix_timestamp
from tokencat.providers.base import ProviderAdapter

SESSION_ID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


class CodexAdapter(ProviderAdapter):
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or Path.home()
        self.codex_dir = self.home / ".codex"
        self.archived_dir = self.codex_dir / "archived_sessions"
        self.session_index_path = self.codex_dir / "session_index.jsonl"

    def detect(self) -> ProviderStatus:
        found_paths: list[Path] = []
        reasons: list[str] = []

        if self.archived_dir.exists():
            found_paths.append(self.archived_dir)
        state_paths = self._state_db_paths()
        found_paths.extend(state_paths)
        if self.session_index_path.exists():
            found_paths.append(self.session_index_path)

        if found_paths:
            reasons.append("Detected local Codex telemetry sources in ~/.codex.")
            return ProviderStatus(
                provider=ProviderName.CODEX,
                status=ProviderSupportLevel.SUPPORTED,
                found_paths=found_paths,
                reasons=reasons,
            )

        return ProviderStatus(
            provider=ProviderName.CODEX,
            status=ProviderSupportLevel.NOT_FOUND,
            reasons=["No Codex local telemetry sources found under ~/.codex."],
        )

    def scan(self, filters: ScanFilters) -> list[SessionRecord]:
        title_index = self._load_session_index()
        sqlite_rows = self._load_state_rows()
        sessions = self._load_archived_sessions(title_index)

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
                )
                sessions[session_id] = record
            else:
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

        return list(sessions.values())

    def _load_archived_sessions(self, title_index: dict[str, str]) -> dict[str, SessionRecord]:
        sessions: dict[str, SessionRecord] = {}
        if not self.archived_dir.exists():
            return sessions

        for path in sorted(self.archived_dir.glob("*.jsonl")):
            session = self._parse_archived_session(path, title_index)
            if session is not None:
                sessions[session.provider_session_id] = session
        return sessions

    def _parse_archived_session(self, path: Path, title_index: dict[str, str]) -> SessionRecord | None:
        session_id = _session_id_from_name(path.name)
        current_model: str | None = None
        record: SessionRecord | None = None
        first_seen = None
        last_seen = None

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
                event_payload = payload.get("payload") or {}

                if event_type == "session_meta":
                    session_id = event_payload.get("id") or session_id
                    if session_id is None:
                        continue
                    record = record or self._new_record(session_id)
                    record.started_at = _pick_earliest(record.started_at, parse_iso_datetime(event_payload.get("timestamp")))
                    record.cwd = record.cwd or event_payload.get("cwd")
                    record.title = record.title or title_index.get(session_id)
                    for key in ("source", "model_provider", "cli_version"):
                        value = event_payload.get(key)
                        if value is not None:
                            record.metadata[key] = value
                    continue

                if event_type == "turn_context":
                    model = event_payload.get("model")
                    if model:
                        current_model = model
                        if session_id:
                            record = record or self._new_record(session_id)
                            record.model_usage.setdefault(model, ModelUsage(model=model, tokens=TokenTotals.zero()))
                    continue

                if event_type == "event_msg" and event_payload.get("type") == "token_count":
                    if session_id is None:
                        continue
                    record = record or self._new_record(session_id)
                    info_payload = event_payload.get("info")
                    if not isinstance(info_payload, dict):
                        continue
                    token_payload = info_payload.get("last_token_usage") or {}
                    if not isinstance(token_payload, dict):
                        continue
                    tokens = TokenTotals(
                        input=token_payload.get("input_tokens"),
                        output=token_payload.get("output_tokens"),
                        cached=token_payload.get("cached_input_tokens"),
                        reasoning=token_payload.get("reasoning_output_tokens"),
                        tool=token_payload.get("tool_tokens"),
                        total=token_payload.get("total_tokens"),
                    )
                    record.token_totals.add(tokens)
                    if current_model:
                        model_usage = record.model_usage.setdefault(current_model, ModelUsage(model=current_model, tokens=TokenTotals.zero()))
                        model_usage.add(tokens, message_count=1)

        if record is None and session_id is not None:
            record = self._new_record(session_id)
        if record is None:
            return None

        record.started_at = _pick_earliest(record.started_at, first_seen)
        record.updated_at = _pick_latest(record.updated_at, last_seen)
        record.title = record.title or title_index.get(record.provider_session_id)
        record.source_refs.append(path)
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
