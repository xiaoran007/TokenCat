from __future__ import annotations

import json
import os
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
from tokencat.core.time import parse_iso_datetime
from tokencat.providers.base import ProviderAdapter

CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"


@dataclass(slots=True)
class ClaudeRoot:
    root: Path
    label: str

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"


class ClaudeAdapter(ProviderAdapter):
    def __init__(self, home: Path | None = None, env: dict[str, str] | None = None) -> None:
        self.home = home or Path.home()
        self.env = env if env is not None else os.environ

    def detect(self) -> ProviderStatus:
        roots, invalid_roots, env_override = self._discover_roots()
        session_paths = self._session_paths(roots)
        found_paths = [root.root for root in roots]
        reasons: list[str] = []
        warnings = [f"Ignoring invalid {CLAUDE_CONFIG_DIR_ENV} entry: {path}" for path in invalid_roots]

        modern_roots = [root.root for root in roots if root.label == "modern"]
        legacy_roots = [root.root for root in roots if root.label == "legacy"]
        env_roots = [root.root for root in roots if root.label == "env"]

        if modern_roots:
            reasons.append("Detected Claude Code data roots under ~/.config/claude.")
        if legacy_roots:
            reasons.append("Detected legacy Claude Code data roots under ~/.claude.")
        if env_roots and env_override:
            reasons.append(f"Detected Claude Code data roots from {CLAUDE_CONFIG_DIR_ENV}.")

        if session_paths:
            reasons.append("Detected Claude Code session JSONL files under projects/.")
            status = ProviderSupportLevel.SUPPORTED
        elif roots:
            reasons.append("Claude Code data roots were found, but no session JSONL files were detected.")
            status = ProviderSupportLevel.PARTIAL
        else:
            reasons.append("No Claude Code local telemetry sources found under ~/.config/claude, ~/.claude, or CLAUDE_CONFIG_DIR.")
            status = ProviderSupportLevel.NOT_FOUND

        return ProviderStatus(
            provider=ProviderName.CLAUDE,
            status=status,
            found_paths=found_paths,
            reasons=reasons,
            warnings=warnings,
        )

    def scan(self, filters: ScanFilters) -> list[SessionRecord]:
        roots, _, _ = self._discover_roots()
        sessions: dict[str, SessionRecord] = {}
        for root in roots:
            for path in self._session_paths([root]):
                record = self._parse_session_file(root, path)
                if record is None:
                    continue
                existing = sessions.get(record.provider_session_id)
                if existing is None:
                    sessions[record.provider_session_id] = record
                else:
                    sessions[record.provider_session_id] = _prefer_richer_record(existing, record)
        return list(sessions.values())

    def _discover_roots(self) -> tuple[list[ClaudeRoot], list[Path], bool]:
        env_value = (self.env.get(CLAUDE_CONFIG_DIR_ENV) or "").strip()
        roots: list[ClaudeRoot] = []
        invalid_roots: list[Path] = []
        seen: set[Path] = set()

        def add_root(candidate: Path, label: str, *, track_invalid: bool) -> None:
            resolved = candidate.expanduser().resolve()
            projects_dir = resolved / "projects"
            if resolved in seen:
                return
            if resolved.is_dir() and projects_dir.is_dir():
                seen.add(resolved)
                roots.append(ClaudeRoot(root=resolved, label=label))
            elif track_invalid:
                invalid_roots.append(resolved)

        if env_value:
            for raw_path in env_value.split(","):
                stripped = raw_path.strip()
                if not stripped:
                    continue
                add_root(Path(stripped), "env", track_invalid=True)
            return roots, invalid_roots, True

        xdg_config_home = Path((self.env.get("XDG_CONFIG_HOME") or str(self.home / ".config"))).expanduser()
        add_root(xdg_config_home / "claude", "modern", track_invalid=False)
        add_root(self.home / ".claude", "legacy", track_invalid=False)
        return roots, invalid_roots, False

    def _session_paths(self, roots: list[ClaudeRoot]) -> list[Path]:
        paths: list[Path] = []
        for root in roots:
            paths.extend(sorted(root.projects_dir.rglob("*.jsonl")))
        return paths

    def _parse_session_file(self, root: ClaudeRoot, path: Path) -> SessionRecord | None:
        relative_path = path.relative_to(root.projects_dir)
        is_subagent = "subagents" in relative_path.parts
        parent_session_from_path = _parent_session_id_from_path(relative_path) if is_subagent else None
        session_id = parent_session_from_path if is_subagent else None
        agent_id = path.stem if is_subagent else None
        cwd: str | None = None
        title: str | None = None
        version: str | None = None
        git_branch: str | None = None
        entrypoint: str | None = None
        is_sidechain = is_subagent
        events: dict[str, tuple[int, datetime | None, dict[str, object], str | None]] = {}

        try:
            handle = path.open("r", encoding="utf-8")
        except OSError:
            return None

        with handle:
            for index, raw_line in enumerate(handle):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue

                session_id = _coalesce_string(_as_non_empty_string(payload.get("sessionId")), session_id)
                agent_id = _coalesce_string(_as_non_empty_string(payload.get("agentId")), agent_id)
                cwd = _coalesce_string(_as_non_empty_string(payload.get("cwd")), cwd)
                title = _coalesce_string(_as_non_empty_string(payload.get("slug")), title)
                version = _coalesce_string(_as_non_empty_string(payload.get("version")), version)
                git_branch = _coalesce_string(_as_non_empty_string(payload.get("gitBranch")), git_branch)
                entrypoint = _coalesce_string(_as_non_empty_string(payload.get("entrypoint")), entrypoint)
                is_sidechain = is_sidechain or bool(payload.get("isSidechain"))

                if payload.get("type") != "assistant" or payload.get("isApiErrorMessage") is True:
                    continue

                message = payload.get("message")
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue

                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue

                model = _as_non_empty_string(message.get("model"))
                if model == "<synthetic>":
                    continue

                timestamp = parse_iso_datetime(_as_non_empty_string(payload.get("timestamp")))
                message_id = _as_non_empty_string(message.get("id")) or f"__line__:{index}"
                events[message_id] = (index, timestamp, usage, model)

        if not events:
            return None

        session_kind = "subagent" if is_subagent else "main"
        if session_id is None:
            session_id = parent_session_from_path or path.stem
        if is_subagent:
            agent_id = agent_id or path.stem
            provider_session_id = f"{session_id}#agent:{agent_id}"
        else:
            provider_session_id = session_id

        record = SessionRecord(
            provider=ProviderName.CLAUDE,
            provider_session_id=provider_session_id,
            anon_session_id=anonymize_session_id(ProviderName.CLAUDE, provider_session_id),
            started_at=None,
            updated_at=None,
            token_totals=TokenTotals.zero(),
            source_refs=[path],
            title=title,
            cwd=cwd,
            metadata={
                "session_kind": session_kind,
                "source_root": str(root.root),
            },
        )
        if version is not None:
            record.metadata["version"] = version
        if git_branch is not None:
            record.metadata["git_branch"] = git_branch
        if entrypoint is not None:
            record.metadata["entrypoint"] = entrypoint
        if is_sidechain:
            record.metadata["is_sidechain"] = "true"
        if is_subagent and agent_id is not None:
            record.metadata["agent_id"] = agent_id
        if is_subagent:
            record.metadata["parent_session_id"] = session_id

        unattributed_tokens = False
        for _, timestamp, usage_payload, model in sorted(events.values(), key=lambda item: ((item[1] or parse_iso_datetime("1970-01-01T00:00:00Z")), item[0])):
            tokens = _tokens_from_usage(usage_payload)
            if tokens.total == 0 and tokens.input == 0 and tokens.output == 0:
                continue
            record.token_totals.add(tokens)
            if timestamp is not None:
                record.started_at = _pick_earliest(record.started_at, timestamp)
                record.updated_at = _pick_latest(record.updated_at, timestamp)
            if model is None:
                unattributed_tokens = True
                if timestamp is not None:
                    record.usage_slices.append(UsageSlice(timestamp=timestamp, model=None, tokens=tokens, message_count=1))
                continue

            usage = record.model_usage.setdefault(model, ModelUsage(model=model, tokens=TokenTotals.zero()))
            usage.add(tokens, message_count=1)
            usage.attribution_status = "exact"
            if timestamp is not None:
                record.usage_slices.append(
                    UsageSlice(
                        timestamp=timestamp,
                        model=model,
                        tokens=tokens,
                        message_count=1,
                        attribution_status="exact",
                    )
                )

        if record.model_usage:
            record.attribution_status = "partial" if unattributed_tokens else "exact"
        elif (record.token_totals.total or 0) > 0:
            record.attribution_status = "unattributed"
        else:
            return None

        if record.started_at is None and record.updated_at is None:
            timestamps = [timestamp for _, timestamp, _, _ in events.values() if timestamp is not None]
            if timestamps:
                record.started_at = min(timestamps)
                record.updated_at = max(timestamps)

        return record


def _as_non_empty_string(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _coalesce_string(candidate: str | None, current: str | None) -> str | None:
    return candidate if candidate is not None else current


def _tokens_from_usage(payload: dict[str, object]) -> TokenTotals:
    input_tokens = _as_int(payload.get("input_tokens"))
    cache_creation_tokens = _as_int(payload.get("cache_creation_input_tokens"))
    cache_read_tokens = _as_int(payload.get("cache_read_input_tokens"))
    output_tokens = _as_int(payload.get("output_tokens"))
    total_input_tokens = input_tokens + cache_creation_tokens + cache_read_tokens
    return TokenTotals(
        input=total_input_tokens,
        output=output_tokens,
        cached=cache_read_tokens,
        total=total_input_tokens + output_tokens,
    )


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _pick_latest(current: object, candidate: object):
    if current is None:
        return candidate
    if candidate is None:
        return current
    return max(current, candidate)


def _pick_earliest(current: object, candidate: object):
    if current is None:
        return candidate
    if candidate is None:
        return current
    return min(current, candidate)


def _parent_session_id_from_path(relative_path: Path) -> str | None:
    parts = relative_path.parts
    try:
        subagents_index = parts.index("subagents")
    except ValueError:
        return None
    if subagents_index <= 0:
        return None
    return parts[subagents_index - 1]


def _prefer_richer_record(existing: SessionRecord, candidate: SessionRecord) -> SessionRecord:
    def score(record: SessionRecord) -> tuple[int, int, int, int, str]:
        return (
            record.token_totals.total or 0,
            len(record.usage_slices),
            len(record.model_usage),
            len(record.metadata),
            (record.updated_at or record.started_at or parse_iso_datetime("1970-01-01T00:00:00Z")).isoformat(),
        )

    winner = candidate if score(candidate) > score(existing) else existing
    other = existing if winner is candidate else candidate

    merged_refs = list(dict.fromkeys([*winner.source_refs, *other.source_refs]))
    winner.source_refs = merged_refs
    if winner.title is None:
        winner.title = other.title
    if winner.cwd is None:
        winner.cwd = other.cwd
    for key, value in other.metadata.items():
        winner.metadata.setdefault(key, value)
    return winner
