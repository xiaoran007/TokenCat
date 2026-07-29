from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tokencat.core.models import ModelUsage, ProviderName, ProviderStatus, ProviderSupportLevel, ScanFilters, SessionRecord, TokenTotals, UsageSlice
from tokencat.core.privacy import anonymize_session_id
from tokencat.providers.base import ProviderAdapter


@dataclass
class _GenerationUsage:
    timestamp: datetime | None
    model: str | None
    tokens: TokenTotals


class AntigravityAdapter(ProviderAdapter):
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or Path.home()
        gemini_dir = self.home / ".gemini"
        self.data_roots = (
            gemini_dir / "antigravity",
            gemini_dir / "antigravity-cli",
        )

    def detect(self) -> ProviderStatus:
        found_roots = [root for root in self.data_roots if root.exists()]
        databases = self._conversation_databases()

        if databases:
            return ProviderStatus(
                provider=ProviderName.ANTIGRAVITY,
                status=ProviderSupportLevel.SUPPORTED,
                found_paths=found_roots,
                reasons=["Detected Antigravity conversation databases under ~/.gemini."],
            )

        if found_roots:
            return ProviderStatus(
                provider=ProviderName.ANTIGRAVITY,
                status=ProviderSupportLevel.PARTIAL,
                found_paths=found_roots,
                reasons=["Antigravity local state exists, but no conversation databases were found."],
            )

        return ProviderStatus(
            provider=ProviderName.ANTIGRAVITY,
            status=ProviderSupportLevel.NOT_FOUND,
            reasons=["No Antigravity local state found under ~/.gemini."],
        )

    def scan(self, filters: ScanFilters) -> list[SessionRecord]:
        sessions: list[SessionRecord] = []
        for path in self._conversation_databases():
            session = self._parse_session(path)
            if session is not None:
                sessions.append(session)
        return sessions

    def _conversation_databases(self) -> list[Path]:
        databases: dict[str, Path] = {}
        for root in self.data_roots:
            conversations_dir = root / "conversations"
            if not conversations_dir.exists():
                continue
            for path in sorted(conversations_dir.glob("*.db")):
                databases.setdefault(path.stem, path)
        return sorted(databases.values(), key=lambda path: path.stem)

    def _parse_session(self, path: Path) -> SessionRecord | None:
        try:
            connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
            try:
                rows = connection.execute("SELECT data FROM gen_metadata ORDER BY idx").fetchall()
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            return None

        generations: list[_GenerationUsage] = []
        for (data,) in rows:
            if not isinstance(data, (bytes, bytearray, memoryview)):
                continue
            try:
                generation = _parse_generation(bytes(data))
            except ValueError:
                continue
            if generation is not None:
                generations.append(generation)

        if not generations:
            return None

        session_id = path.stem
        timestamps = [generation.timestamp for generation in generations if generation.timestamp is not None]
        record = SessionRecord(
            provider=ProviderName.ANTIGRAVITY,
            provider_session_id=session_id,
            anon_session_id=anonymize_session_id(ProviderName.ANTIGRAVITY, session_id),
            started_at=min(timestamps) if timestamps else None,
            updated_at=max(timestamps) if timestamps else None,
            token_totals=TokenTotals.zero(),
            source_refs=[path],
            metadata={"generation_count": len(generations)},
            attribution_status="exact",
        )

        for generation in generations:
            record.token_totals.add(generation.tokens)
            if generation.model is not None:
                usage = record.model_usage.setdefault(
                    generation.model,
                    ModelUsage(model=generation.model, tokens=TokenTotals.zero(), attribution_status="exact"),
                )
                usage.add(generation.tokens, message_count=1)
            if generation.timestamp is not None:
                record.usage_slices.append(
                    UsageSlice(
                        timestamp=generation.timestamp,
                        model=generation.model,
                        tokens=generation.tokens,
                        message_count=1,
                        attribution_status="exact" if generation.model is not None else "unattributed",
                    )
                )

        return record


def _parse_generation(data: bytes) -> _GenerationUsage | None:
    envelope = _first_bytes(_decode_fields(data), 1)
    if envelope is None:
        return None

    envelope_fields = _decode_fields(envelope)
    usage_payload = _first_bytes(envelope_fields, 4)
    if usage_payload is None:
        return None

    usage_fields = _decode_fields(usage_payload)
    fixed_input = _first_varint(usage_fields, 1) or 0
    non_cached_input = _first_varint(usage_fields, 2) or 0
    output = _first_varint(usage_fields, 3) or 0
    cached_input = _first_varint(usage_fields, 5) or 0
    fixed_overhead = _first_varint(usage_fields, 6) or 0
    input_tokens = fixed_input + non_cached_input + cached_input + fixed_overhead
    tokens = TokenTotals(
        input=input_tokens,
        output=output,
        cached=cached_input,
        reasoning=0,
        tool=0,
        total=input_tokens + output,
    )

    model_payload = _first_bytes(envelope_fields, 19)
    model = _decode_text(model_payload) if model_payload is not None else None
    timestamp = _parse_timestamp(_first_bytes(envelope_fields, 9))
    return _GenerationUsage(timestamp=timestamp, model=model, tokens=tokens)


def _parse_timestamp(timing_payload: bytes | None) -> datetime | None:
    if timing_payload is None:
        return None
    timestamp_payload = _first_bytes(_decode_fields(timing_payload), 4)
    if timestamp_payload is None:
        return None
    timestamp_fields = _decode_fields(timestamp_payload)
    seconds = _first_varint(timestamp_fields, 1)
    if seconds is None:
        return None
    nanos = _first_varint(timestamp_fields, 2) or 0
    try:
        return datetime.fromtimestamp(seconds + nanos / 1_000_000_000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _decode_fields(data: bytes) -> list[tuple[int, int, int | bytes]]:
    fields: list[tuple[int, int, int | bytes]] = []
    offset = 0
    while offset < len(data):
        tag, offset = _read_varint(data, offset)
        field_number = tag >> 3
        wire_type = tag & 0x07
        if field_number == 0:
            raise ValueError("Invalid protobuf field number.")

        if wire_type == 0:
            value, offset = _read_varint(data, offset)
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise ValueError("Truncated protobuf fixed64 field.")
            value = data[offset:end]
            offset = end
        elif wire_type == 2:
            size, offset = _read_varint(data, offset)
            end = offset + size
            if end > len(data):
                raise ValueError("Truncated protobuf bytes field.")
            value = data[offset:end]
            offset = end
        elif wire_type == 5:
            end = offset + 4
            if end > len(data):
                raise ValueError("Truncated protobuf fixed32 field.")
            value = data[offset:end]
            offset = end
        else:
            raise ValueError("Unsupported protobuf wire type.")
        fields.append((field_number, wire_type, value))
    return fields


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data) and shift < 70:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise ValueError("Invalid protobuf varint.")


def _first_varint(fields: list[tuple[int, int, int | bytes]], field_number: int) -> int | None:
    for number, wire_type, value in fields:
        if number == field_number and wire_type == 0 and isinstance(value, int):
            return value
    return None


def _first_bytes(fields: list[tuple[int, int, int | bytes]], field_number: int) -> bytes | None:
    for number, wire_type, value in fields:
        if number == field_number and wire_type == 2 and isinstance(value, bytes):
            return value
    return None


def _decode_text(data: bytes) -> str | None:
    try:
        value = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    return value or None
