from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime
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
from tokencat.core.time import parse_unix_timestamp
from tokencat.providers.base import ProviderAdapter


MESSAGE_USAGE_QUERY = """
SELECT s.id, s.title, s.directory, s.time_created, s.time_updated,
       COALESCE(json_extract(m.data, '$.time.completed'), m.time_updated),
       json_extract(m.data, '$.providerID'), json_extract(m.data, '$.modelID'),
       json_extract(m.data, '$.tokens.input'),
       json_extract(m.data, '$.tokens.output'),
       json_extract(m.data, '$.tokens.reasoning'),
       json_extract(m.data, '$.tokens.cache.read'),
       json_extract(m.data, '$.tokens.cache.write'),
       json_extract(m.data, '$.tokens.total')
FROM message AS m
JOIN session AS s ON s.id = m.session_id
WHERE json_extract(m.data, '$.role') = 'assistant'
  AND json_type(m.data, '$.tokens') = 'object'
"""


class OpenCodeAdapter(ProviderAdapter):
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or Path.home()
        data_home = self.home / ".local" / "share"
        if home is None and os.environ.get("XDG_DATA_HOME"):
            data_home = Path(os.environ["XDG_DATA_HOME"])
        self.db_path = data_home / "opencode" / "opencode.db"

    def detect(self) -> ProviderStatus:
        if not self.db_path.is_file():
            return ProviderStatus(
                provider=ProviderName.OPENCODE,
                status=ProviderSupportLevel.NOT_FOUND,
                reasons=["No OpenCode SQLite database was found."],
            )

        try:
            with closing(self._connect()) as connection:
                has_usage = connection.execute(
                    "SELECT 1 FROM message WHERE json_extract(data, '$.role') = 'assistant' "
                    "AND json_type(data, '$.tokens') = 'object' LIMIT 1"
                ).fetchone() is not None
        except sqlite3.Error as exc:
            return ProviderStatus(
                provider=ProviderName.OPENCODE,
                status=ProviderSupportLevel.PARTIAL,
                found_paths=[self.db_path],
                reasons=["OpenCode SQLite database could not be read."],
                warnings=[f"OpenCode database error: {exc}"],
            )

        return ProviderStatus(
            provider=ProviderName.OPENCODE,
            status=ProviderSupportLevel.SUPPORTED if has_usage else ProviderSupportLevel.PARTIAL,
            found_paths=[self.db_path],
            reasons=[
                "Detected assistant token usage in OpenCode's local SQLite database."
                if has_usage else "OpenCode database contains no assistant token usage yet."
            ],
        )

    def scan(self, filters: ScanFilters) -> list[SessionRecord]:
        if not self.db_path.is_file():
            return []
        try:
            return self._scan_database()
        except sqlite3.Error:
            return []

    def _scan_database(self) -> list[SessionRecord]:
        records: dict[str, SessionRecord] = {}
        with closing(self._connect()) as connection:
            for row in connection.execute(MESSAGE_USAGE_QUERY):
                (
                    session_id, title, directory, created_ms, updated_ms,
                    message_ms, provider_id, model_id, *raw_tokens,
                ) = row
                record = records.get(session_id)
                if record is None:
                    record = SessionRecord(
                        provider=ProviderName.OPENCODE,
                        provider_session_id=session_id,
                        anon_session_id=anonymize_session_id(ProviderName.OPENCODE, session_id),
                        started_at=_from_milliseconds(created_ms),
                        updated_at=_from_milliseconds(updated_ms),
                        token_totals=TokenTotals.zero(),
                        source_refs=[self.db_path],
                        title=title,
                        cwd=directory,
                        metadata={"source": "opencode_sqlite", "request_count": 0},
                    )
                    records[session_id] = record

                input_tokens, output_tokens, reasoning_tokens, cache_read, cache_write, reported_total = (
                    _count(value) for value in raw_tokens
                )
                total = reported_total or input_tokens + output_tokens + reasoning_tokens + cache_read + cache_write
                tokens = TokenTotals(
                    input=input_tokens + cache_read + cache_write,
                    output=output_tokens + reasoning_tokens,
                    reasoning=reasoning_tokens,
                    cached=cache_read,
                    total=total,
                )
                record.token_totals.add(tokens)
                record.metadata["request_count"] = int(record.metadata["request_count"]) + 1

                model = _model_name(provider_id, model_id)
                message_time = _from_milliseconds(message_ms)
                if message_time is not None:
                    record.usage_slices.append(
                        UsageSlice(
                            timestamp=message_time,
                            model=model,
                            tokens=tokens,
                            message_count=1,
                            attribution_status="exact" if model else None,
                        )
                    )

                if model is None:
                    record.attribution_status = "partial" if record.model_usage else "unattributed"
                    continue
                usage = record.model_usage.setdefault(
                    model,
                    ModelUsage(model=model, tokens=TokenTotals.zero(), attribution_status="exact"),
                )
                usage.add(tokens, message_count=1)
                record.attribution_status = (
                    "partial" if record.attribution_status in {"partial", "unattributed"} else "exact"
                )

        return list(records.values())

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
        return connection


def _from_milliseconds(value: int | None) -> datetime | None:
    return parse_unix_timestamp(value / 1000) if value is not None else None


def _count(value: object) -> int:
    return max(int(value), 0) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _model_name(provider_id: object, model_id: object) -> str | None:
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    model = model_id.strip()
    if not isinstance(provider_id, str) or not provider_id.strip() or "/" in model:
        return model
    return f"{provider_id.strip()}/{model}"
