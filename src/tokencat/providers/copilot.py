from __future__ import annotations

import json
import shutil
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
)
from tokencat.core.privacy import anonymize_session_id
from tokencat.core.time import parse_iso_datetime
from tokencat.providers.base import ProviderAdapter


class CopilotAdapter(ProviderAdapter):
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or Path.home()
        self.copilot_dir = self.home / ".copilot"
        self.copilot_session_state_dir = self.copilot_dir / "session-state"
        self.config_dir = self.home / ".config"
        self.library_dir = self.home / "Library" / "Application Support"
        self.vscode_workspace_storage_dir = self.library_dir / "Code" / "User" / "workspaceStorage"

    def detect(self) -> ProviderStatus:
        found_paths: list[Path] = []
        ignored_paths: list[Path] = []
        reasons: list[str] = []
        warnings: list[str] = []

        binary = self._binary_path()
        if binary is not None:
            found_paths.append(binary)

        cli_paths = [path for path in self._candidate_cli_paths() if path.exists()]
        found_paths.extend(cli_paths)

        vscode_session_paths = self._session_paths()
        if vscode_session_paths:
            found_paths.append(self.vscode_workspace_storage_dir)

        cli_session_dirs = self._cli_session_dirs()
        if cli_session_dirs:
            found_paths.append(self.copilot_session_state_dir)

        for path in self._plugin_paths():
            if path.exists():
                ignored_paths.append(path)

        vscode_records = self._scan_session_paths(vscode_session_paths) if vscode_session_paths else []
        cli_inspections = [self._inspect_cli_session_dir(path) for path in cli_session_dirs]
        cli_records = [record for record, _, _ in cli_inspections if record is not None]

        has_vscode_token_usage = any((record.token_totals.total or 0) > 0 for record in vscode_records)
        has_cli_token_usage = any((record.token_totals.total or 0) > 0 for record in cli_records)
        has_cli_shutdown_summary = any(has_shutdown_summary for _, _, has_shutdown_summary in cli_inspections)
        has_cli_activity = any(has_activity for _, has_activity, _ in cli_inspections)

        if has_vscode_token_usage or has_cli_token_usage:
            if has_vscode_token_usage:
                reasons.append("Detected VS Code Copilot chat sessions with local token usage counters.")
            if has_cli_token_usage:
                reasons.append("Detected Copilot CLI session-state files with local token usage counters.")
            return ProviderStatus(
                provider=ProviderName.COPILOT,
                status=ProviderSupportLevel.SUPPORTED,
                found_paths=_dedupe_paths(found_paths),
                ignored_paths=_dedupe_paths(ignored_paths),
                reasons=reasons,
                warnings=warnings,
            )

        if vscode_records or cli_records:
            if vscode_records:
                reasons.append("Detected VS Code Copilot chat sessions, but the local session store does not include token usage for them yet.")
            if cli_records:
                reasons.append("Detected Copilot CLI shutdown summaries, but they do not include usable token counters yet.")
            return ProviderStatus(
                provider=ProviderName.COPILOT,
                status=ProviderSupportLevel.PARTIAL,
                found_paths=_dedupe_paths(found_paths),
                ignored_paths=_dedupe_paths(ignored_paths),
                reasons=reasons,
                warnings=warnings,
            )

        if vscode_session_paths or has_cli_activity or has_cli_shutdown_summary:
            if vscode_session_paths:
                reasons.append("Detected VS Code Copilot session files, but they only contain empty scaffold sessions so far.")
            if has_cli_activity and not has_cli_shutdown_summary:
                reasons.append("Detected Copilot CLI session-state files, but only active sessions without shutdown summaries were found.")
            elif has_cli_shutdown_summary:
                reasons.append("Detected Copilot CLI session-state files, but no complete model metrics were available to scan.")
            return ProviderStatus(
                provider=ProviderName.COPILOT,
                status=ProviderSupportLevel.PARTIAL,
                found_paths=_dedupe_paths(found_paths),
                ignored_paths=_dedupe_paths(ignored_paths),
                reasons=reasons,
            )

        if found_paths:
            reasons.append("Potential Copilot install artifacts were detected, but no stable local token session store was found.")
            return ProviderStatus(
                provider=ProviderName.COPILOT,
                status=ProviderSupportLevel.PARTIAL,
                found_paths=_dedupe_paths(found_paths),
                ignored_paths=_dedupe_paths(ignored_paths),
                reasons=reasons,
                warnings=warnings,
            )

        if ignored_paths:
            return ProviderStatus(
                provider=ProviderName.COPILOT,
                status=ProviderSupportLevel.UNSUPPORTED,
                ignored_paths=_dedupe_paths(ignored_paths),
                reasons=["Only IDE/plugin state was found. No safe Copilot chat session store with token counters was identified."],
            )

        return ProviderStatus(
            provider=ProviderName.COPILOT,
            status=ProviderSupportLevel.NOT_FOUND,
            reasons=["No GitHub Copilot local telemetry source was found."],
        )

    def scan(self, filters: ScanFilters) -> list[SessionRecord]:
        sessions: dict[str, SessionRecord] = {}
        for record in self._scan_session_paths(self._session_paths()):
            sessions[record.provider_session_id] = record
        for record in self._scan_cli_session_dirs(self._cli_session_dirs()):
            existing = sessions.get(record.provider_session_id)
            if existing is None:
                sessions[record.provider_session_id] = record
            else:
                sessions[record.provider_session_id] = _prefer_richer_session(existing, record)
        return list(sessions.values())

    def _scan_session_paths(self, session_paths: list[Path]) -> list[SessionRecord]:
        sessions: dict[str, SessionRecord] = {}
        for path in session_paths:
            record = self._parse_session_file(path)
            if record is None:
                continue
            existing = sessions.get(record.provider_session_id)
            if existing is None:
                sessions[record.provider_session_id] = record
            else:
                sessions[record.provider_session_id] = _prefer_richer_session(existing, record)
        return list(sessions.values())

    def _parse_session_file(self, path: Path) -> SessionRecord | None:
        payload = self._load_session_payload(path)
        if payload is None:
            return None

        session_id = _as_non_empty_string(payload.get("sessionId"))
        if session_id is None:
            return None

        requests = _safe_request_list(payload.get("requests"))
        if not requests:
            return None

        created_at = _parse_timestamp(payload.get("creationDate"))
        first_request_at = None
        last_request_at = None
        record = SessionRecord(
            provider=ProviderName.COPILOT,
            provider_session_id=session_id,
            anon_session_id=anonymize_session_id(ProviderName.COPILOT, session_id),
            started_at=created_at,
            updated_at=created_at,
            token_totals=TokenTotals.zero(),
            source_refs=[path],
            title=_as_non_empty_string(payload.get("customTitle")),
            metadata={
                "request_count": len(requests),
                "source": "vscode_chat_sessions",
            },
        )

        saw_missing_model_usage = False

        for request in requests:
            request_at = _parse_timestamp(request.get("timestamp"))
            first_request_at = _pick_earliest(first_request_at, request_at)
            last_request_at = _pick_latest(last_request_at, request_at)

            model_name = _as_non_empty_string(request.get("modelId"))
            usage_payload = _extract_usage_payload(request.get("result"))
            tokens = _token_totals_from_usage(usage_payload)

            if tokens is not None:
                record.token_totals.add(tokens)

            if model_name is None:
                saw_missing_model_usage = saw_missing_model_usage or tokens is not None
                continue

            usage = record.model_usage.setdefault(
                model_name,
                ModelUsage(model=model_name, tokens=TokenTotals(), attribution_status="exact"),
            )
            if tokens is not None:
                usage.add(tokens, message_count=1)
            else:
                usage.message_count += 1
            usage.attribution_status = "exact"

        record.started_at = _pick_earliest(record.started_at, first_request_at)
        record.updated_at = _pick_latest(record.updated_at, last_request_at)

        if record.model_usage and not saw_missing_model_usage:
            record.attribution_status = "exact"
        elif record.model_usage:
            record.attribution_status = "partial"
        elif (record.token_totals.total or 0) > 0:
            record.attribution_status = "unattributed"

        return record

    def _scan_cli_session_dirs(self, session_dirs: list[Path]) -> list[SessionRecord]:
        sessions: list[SessionRecord] = []
        for path in session_dirs:
            record, _, _ = self._inspect_cli_session_dir(path)
            if record is not None:
                sessions.append(record)
        return sessions

    def _inspect_cli_session_dir(self, session_dir: Path) -> tuple[SessionRecord | None, bool, bool]:
        events_path = session_dir / "events.jsonl"
        if not events_path.is_file():
            return None, False, False

        workspace_metadata = _load_workspace_yaml_metadata(session_dir / "workspace.yaml")
        session_id = _as_non_empty_string(workspace_metadata.get("id")) or session_dir.name
        started_at = _parse_timestamp(workspace_metadata.get("created_at"))
        updated_at = _parse_timestamp(workspace_metadata.get("updated_at"))
        cwd = _as_non_empty_string(workspace_metadata.get("cwd"))

        has_activity = False
        has_shutdown_summary = False
        shutdown_data: dict[str, object] | None = None
        shutdown_timestamp: datetime | None = None

        try:
            handle = events_path.open("r", encoding="utf-8")
        except OSError:
            return None, False, False

        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw_event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw_event, dict):
                    continue

                event_type = _as_non_empty_string(raw_event.get("type"))
                if event_type is None:
                    continue
                has_activity = True
                event_timestamp = _parse_timestamp(raw_event.get("timestamp"))
                data = raw_event.get("data")
                safe_data = data if isinstance(data, dict) else {}

                if event_type == "session.start":
                    session_id = _as_non_empty_string(safe_data.get("sessionId")) or session_id
                    started_at = _pick_earliest(
                        started_at,
                        _parse_timestamp(safe_data.get("startTime")) or event_timestamp,
                    )
                elif event_type == "session.shutdown":
                    has_shutdown_summary = True
                    shutdown_data = safe_data
                    shutdown_timestamp = event_timestamp

        if shutdown_data is None:
            return None, has_activity, has_shutdown_summary

        model_metrics = shutdown_data.get("modelMetrics")
        if not isinstance(model_metrics, dict) or not model_metrics:
            return None, has_activity, has_shutdown_summary

        started_at = _pick_earliest(
            started_at,
            _parse_timestamp(shutdown_data.get("sessionStartTime")),
        )
        updated_at = _pick_latest(updated_at, shutdown_timestamp)

        record = SessionRecord(
            provider=ProviderName.COPILOT,
            provider_session_id=session_id,
            anon_session_id=anonymize_session_id(ProviderName.COPILOT, session_id),
            started_at=started_at,
            updated_at=updated_at,
            token_totals=TokenTotals.zero(),
            source_refs=[events_path],
            primary_model_override=_as_non_empty_string(shutdown_data.get("currentModel")),
            cwd=cwd,
            metadata={"source": "copilot_cli_session_state"},
        )

        total_request_count = 0
        total_cache_write_tokens = 0
        total_request_cost = 0.0

        for model_name, payload in sorted(model_metrics.items()):
            model_id = _as_non_empty_string(model_name)
            if model_id is None or not isinstance(payload, dict):
                continue

            usage_payload = payload.get("usage")
            request_payload = payload.get("requests")
            usage = usage_payload if isinstance(usage_payload, dict) else {}
            requests = request_payload if isinstance(request_payload, dict) else {}

            input_tokens = _safe_int(usage.get("inputTokens")) or 0
            output_tokens = _safe_int(usage.get("outputTokens")) or 0
            cached_tokens = _safe_int(usage.get("cacheReadTokens")) or 0
            cache_write_tokens = _safe_int(usage.get("cacheWriteTokens")) or 0
            request_count = _safe_int(requests.get("count")) or 0
            request_cost = _safe_float(requests.get("cost")) or 0.0

            tokens = TokenTotals(
                input=input_tokens,
                output=output_tokens,
                cached=cached_tokens,
                total=input_tokens + output_tokens,
            )
            record.token_totals.add(tokens)
            record.model_usage[model_id] = ModelUsage(
                model=model_id,
                tokens=tokens,
                message_count=request_count,
                attribution_status="exact",
            )
            total_request_count += request_count
            total_cache_write_tokens += cache_write_tokens
            total_request_cost += request_cost

        if not record.model_usage:
            return None, has_activity, has_shutdown_summary

        record.attribution_status = "exact"
        record.metadata["request_count"] = total_request_count
        premium_requests = _safe_int(shutdown_data.get("totalPremiumRequests"))
        if premium_requests is not None:
            record.metadata["premium_requests"] = premium_requests
        if total_cache_write_tokens:
            record.metadata["cache_write_tokens"] = total_cache_write_tokens
        if total_request_cost:
            record.metadata["request_cost"] = total_request_cost
        shutdown_type = _as_non_empty_string(shutdown_data.get("shutdownType"))
        if shutdown_type is not None:
            record.metadata["shutdown_type"] = shutdown_type
        total_api_duration_ms = _safe_int(shutdown_data.get("totalApiDurationMs"))
        if total_api_duration_ms is not None:
            record.metadata["total_api_duration_ms"] = total_api_duration_ms

        return record, has_activity, has_shutdown_summary

    def _load_session_payload(self, path: Path) -> dict[str, object] | None:
        if path.suffix == ".json":
            try:
                raw_payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            return _safe_session_payload(raw_payload)

        if path.suffix == ".jsonl":
            return self._load_jsonl_session_payload(path)

        return None

    def _load_jsonl_session_payload(self, path: Path) -> dict[str, object] | None:
        state: dict[str, object] = {"requests": []}
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
                    raw_payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw_payload, dict):
                    continue

                if "k" not in raw_payload:
                    snapshot = _safe_session_payload(raw_payload.get("v"))
                    if snapshot is None:
                        continue
                    state = snapshot
                    state.setdefault("requests", [])
                    continue

                patch_path = raw_payload.get("k")
                if not isinstance(patch_path, list):
                    continue
                _apply_jsonl_patch(state, patch_path, raw_payload.get("v"))

        return state if _as_non_empty_string(state.get("sessionId")) is not None else None

    def _session_paths(self) -> list[Path]:
        if not self.vscode_workspace_storage_dir.exists():
            return []

        paths: list[Path] = []
        for path in self.vscode_workspace_storage_dir.glob("*/chatSessions/*"):
            if path.is_file() and path.suffix in {".json", ".jsonl"}:
                paths.append(path)
        return sorted(paths)

    def _cli_session_dirs(self) -> list[Path]:
        if not self.copilot_session_state_dir.exists():
            return []
        return sorted(path for path in self.copilot_session_state_dir.iterdir() if path.is_dir())

    def _binary_path(self) -> Path | None:
        binary = shutil.which("github-copilot") or shutil.which("copilot")
        if binary is None:
            return None
        resolved = Path(binary)
        try:
            resolved.relative_to(self.home)
            return resolved
        except ValueError:
            return None

    def _candidate_cli_paths(self) -> list[Path]:
        return [
            self.copilot_dir,
            self.config_dir / "github-copilot-cli",
            self.config_dir / "copilot-cli",
            self.home / ".local" / "share" / "github-copilot-cli",
            self.library_dir / "GitHub Copilot CLI",
            self.library_dir / "Code" / "User" / "globalStorage" / "github.copilot-chat" / "copilotCli",
        ]

    def _plugin_paths(self) -> list[Path]:
        return [
            self.config_dir / "github-copilot",
            self.library_dir / "GitHub Copilot",
        ]


def _safe_session_payload(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    payload: dict[str, object] = {}
    session_id = _as_non_empty_string(value.get("sessionId"))
    if session_id is not None:
        payload["sessionId"] = session_id
    custom_title = _as_non_empty_string(value.get("customTitle"))
    if custom_title is not None:
        payload["customTitle"] = custom_title
    creation_date = value.get("creationDate")
    if isinstance(creation_date, (int, float)) and not isinstance(creation_date, bool):
        payload["creationDate"] = creation_date
    payload["requests"] = _safe_request_list(value.get("requests"))
    return payload


def _safe_request_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [request for request in (_safe_request(item) for item in value) if request is not None]


def _safe_request(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    request: dict[str, object] = {}
    timestamp = value.get("timestamp")
    if isinstance(timestamp, (int, float, str)) and not isinstance(timestamp, bool):
        request["timestamp"] = timestamp
    model_id = _as_non_empty_string(value.get("modelId"))
    if model_id is not None:
        request["modelId"] = model_id
    result = _safe_result(value.get("result"))
    if result is not None:
        request["result"] = result
    return request


def _safe_result(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    usage = value.get("usage")
    if not isinstance(usage, dict):
        return None
    safe_usage: dict[str, int] = {}
    for key in ("promptTokens", "completionTokens"):
        numeric = _safe_int(usage.get(key))
        if numeric is not None:
            safe_usage[key] = numeric
    return {"usage": safe_usage} if safe_usage else None


def _apply_jsonl_patch(state: dict[str, object], path: list[object], value: object) -> None:
    if not path:
        snapshot = _safe_session_payload(value)
        if snapshot is not None:
            state.clear()
            state.update(snapshot)
            state.setdefault("requests", [])
        return

    key = path[0]
    if key == "requests":
        _apply_request_patch(state, path[1:], value)
        return

    if len(path) != 1 or not isinstance(key, str):
        return

    if key == "sessionId":
        sanitized = _as_non_empty_string(value)
        if sanitized is not None:
            state["sessionId"] = sanitized
    elif key == "customTitle":
        sanitized = _as_non_empty_string(value)
        if sanitized is not None:
            state["customTitle"] = sanitized
    elif key == "creationDate" and isinstance(value, (int, float)) and not isinstance(value, bool):
        state["creationDate"] = value


def _apply_request_patch(state: dict[str, object], path: list[object], value: object) -> None:
    requests = state.setdefault("requests", [])
    if not isinstance(requests, list):
        return

    if not path:
        state["requests"] = _safe_request_list(value)
        return

    index = path[0]
    if not isinstance(index, int):
        return

    _ensure_request_capacity(requests, index + 1)
    current = requests[index]
    if not isinstance(current, dict):
        current = {}
        requests[index] = current

    if len(path) == 1:
        sanitized = _safe_request(value)
        if sanitized is not None:
            requests[index] = _merge_request_state(current, sanitized)
        return

    field = path[1]
    if field == "result":
        sanitized_result = _safe_result(value)
        if sanitized_result is not None:
            current_result = current.get("result")
            if isinstance(current_result, dict):
                current["result"] = {**current_result, **sanitized_result}
            else:
                current["result"] = sanitized_result
    elif field == "modelId":
        sanitized = _as_non_empty_string(value)
        if sanitized is not None:
            current["modelId"] = sanitized
    elif field == "timestamp" and isinstance(value, (int, float, str)) and not isinstance(value, bool):
        current["timestamp"] = value


def _merge_request_state(current: dict[str, object], incoming: dict[str, object]) -> dict[str, object]:
    merged = dict(current)
    for key, value in incoming.items():
        if key == "result" and isinstance(value, dict) and isinstance(merged.get("result"), dict):
            merged["result"] = {**merged["result"], **value}
        else:
            merged[key] = value
    return merged


def _ensure_request_capacity(requests: list[object], size: int) -> None:
    while len(requests) < size:
        requests.append({})


def _extract_usage_payload(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    usage = value.get("usage")
    return usage if isinstance(usage, dict) else None


def _token_totals_from_usage(value: dict[str, object] | None) -> TokenTotals | None:
    if value is None:
        return None
    prompt_tokens = _safe_int(value.get("promptTokens")) or 0
    completion_tokens = _safe_int(value.get("completionTokens")) or 0
    return TokenTotals(
        input=prompt_tokens,
        output=completion_tokens,
        total=prompt_tokens + completion_tokens,
    )


def _safe_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _as_non_empty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=UTC).astimezone()
    if isinstance(value, str):
        return parse_iso_datetime(value)
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


def _load_workspace_yaml_metadata(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    metadata: dict[str, str] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip()
        normalized_value = value.strip()
        if not normalized_key or not normalized_value:
            continue
        metadata[normalized_key] = normalized_value
    return metadata


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            deduped.append(path)
            seen.add(path)
    return deduped


def _prefer_richer_session(existing: SessionRecord, candidate: SessionRecord) -> SessionRecord:
    existing_score = _session_score(existing)
    candidate_score = _session_score(candidate)
    preferred = candidate if candidate_score > existing_score else existing
    fallback = existing if preferred is candidate else candidate

    preferred.started_at = _pick_earliest(preferred.started_at, fallback.started_at)
    preferred.updated_at = _pick_latest(preferred.updated_at, fallback.updated_at)
    if preferred.title is None:
        preferred.title = fallback.title
    if len(preferred.source_refs) < len(fallback.source_refs):
        preferred.source_refs = fallback.source_refs
    for key, value in fallback.metadata.items():
        preferred.metadata.setdefault(key, value)
    return preferred


def _session_score(record: SessionRecord) -> tuple[int, int, int, float]:
    total_tokens = record.token_totals.total or 0
    model_count = len(record.model_usage)
    request_count = int(record.metadata.get("request_count", 0) or 0)
    timestamp = (record.updated_at or record.started_at or datetime.fromtimestamp(0, tz=UTC).astimezone()).timestamp()
    return (total_tokens, model_count, request_count, timestamp)
