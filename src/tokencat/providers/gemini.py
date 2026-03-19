from __future__ import annotations

import json
from pathlib import Path

from tokencat.core.models import ModelUsage, ProviderName, ProviderStatus, ProviderSupportLevel, ScanFilters, SessionRecord, TokenTotals, UsageSlice
from tokencat.core.privacy import anonymize_session_id
from tokencat.core.time import parse_iso_datetime
from tokencat.providers.base import ProviderAdapter


class GeminiAdapter(ProviderAdapter):
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or Path.home()
        self.gemini_dir = self.home / ".gemini"
        self.tmp_dir = self.gemini_dir / "tmp"
        self.settings_path = self.gemini_dir / "settings.json"

    def detect(self) -> ProviderStatus:
        found_paths: list[Path] = []
        reasons: list[str] = []

        if self.settings_path.exists():
            found_paths.append(self.settings_path)
        if self.tmp_dir.exists():
            found_paths.append(self.tmp_dir)

        if any(self.tmp_dir.rglob("session-*.json")):
            reasons.append("Detected Gemini CLI chat session files under ~/.gemini/tmp.")
            return ProviderStatus(
                provider=ProviderName.GEMINI,
                status=ProviderSupportLevel.SUPPORTED,
                found_paths=found_paths,
                reasons=reasons,
            )

        if found_paths:
            return ProviderStatus(
                provider=ProviderName.GEMINI,
                status=ProviderSupportLevel.PARTIAL,
                found_paths=found_paths,
                reasons=["Gemini settings exist, but no session chat files were found."],
            )

        return ProviderStatus(
            provider=ProviderName.GEMINI,
            status=ProviderSupportLevel.NOT_FOUND,
            reasons=["No Gemini CLI local state found under ~/.gemini."],
        )

    def scan(self, filters: ScanFilters) -> list[SessionRecord]:
        sessions: list[SessionRecord] = []
        default_model = self._load_default_model()
        if not self.tmp_dir.exists():
            return sessions

        for path in sorted(self.tmp_dir.rglob("session-*.json")):
            session = self._parse_session(path, default_model)
            if session is not None:
                sessions.append(session)
        return sessions

    def _parse_session(self, path: Path, default_model: str | None) -> SessionRecord | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        session_id = payload.get("sessionId")
        if not session_id:
            return None

        record = SessionRecord(
            provider=ProviderName.GEMINI,
            provider_session_id=session_id,
            anon_session_id=anonymize_session_id(ProviderName.GEMINI, session_id),
            started_at=parse_iso_datetime(payload.get("startTime")),
            updated_at=parse_iso_datetime(payload.get("lastUpdated")),
            token_totals=TokenTotals.zero(),
            source_refs=[path],
            metadata={"project_hash": payload.get("projectHash"), "default_model": default_model},
        )

        for message in payload.get("messages", []):
            model = message.get("model")
            token_payload = message.get("tokens")
            if not model or not isinstance(token_payload, dict):
                continue
            message_timestamp = parse_iso_datetime(message.get("timestamp"))
            tokens = TokenTotals(
                input=token_payload.get("input"),
                output=token_payload.get("output"),
                cached=token_payload.get("cached"),
                reasoning=token_payload.get("thoughts"),
                tool=token_payload.get("tool"),
                total=token_payload.get("total"),
            )
            record.token_totals.add(tokens)
            usage = record.model_usage.setdefault(model, ModelUsage(model=model, tokens=TokenTotals.zero()))
            usage.add(tokens, message_count=1)
            if message_timestamp is not None:
                record.usage_slices.append(
                    UsageSlice(
                        timestamp=message_timestamp,
                        model=model,
                        tokens=tokens,
                        message_count=1,
                        attribution_status="exact",
                    )
                )

        return record

    def _load_default_model(self) -> str | None:
        if not self.settings_path.exists():
            return None
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload.get("model", {}).get("name")
