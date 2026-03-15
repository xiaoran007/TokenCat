from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class ProviderName(StrEnum):
    CODEX = "codex"
    GEMINI = "gemini"
    COPILOT = "copilot"


class ProviderSupportLevel(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    NOT_FOUND = "not_found"


@dataclass(slots=True)
class TokenTotals:
    input: int | None = None
    output: int | None = None
    cached: int | None = None
    reasoning: int | None = None
    tool: int | None = None
    total: int | None = None

    @classmethod
    def zero(cls) -> "TokenTotals":
        return cls(input=0, output=0, cached=0, reasoning=0, tool=0, total=0)

    def add(self, other: "TokenTotals") -> None:
        for field_name in ("input", "output", "cached", "reasoning", "tool", "total"):
            current = getattr(self, field_name)
            incoming = getattr(other, field_name)
            if incoming is None:
                continue
            if current is None:
                setattr(self, field_name, incoming)
            else:
                setattr(self, field_name, current + incoming)

    def is_empty(self) -> bool:
        return all(getattr(self, name) is None for name in self.__dataclass_fields__)

    def to_dict(self) -> dict[str, int | None]:
        return {
            "input": self.input,
            "output": self.output,
            "cached": self.cached,
            "reasoning": self.reasoning,
            "tool": self.tool,
            "total": self.total,
        }


@dataclass(slots=True)
class ModelUsage:
    model: str
    tokens: TokenTotals = field(default_factory=TokenTotals)
    message_count: int = 0

    def add(self, tokens: TokenTotals, message_count: int = 0) -> None:
        self.tokens.add(tokens)
        self.message_count += message_count


@dataclass(slots=True)
class SessionRecord:
    provider: ProviderName
    provider_session_id: str
    anon_session_id: str
    started_at: datetime | None
    updated_at: datetime | None
    token_totals: TokenTotals
    source_refs: list[Path] = field(default_factory=list)
    model_usage: dict[str, ModelUsage] = field(default_factory=dict)
    title: str | None = None
    cwd: str | None = None
    metadata: dict[str, str | int | float | None] = field(default_factory=dict)

    @property
    def models(self) -> list[str]:
        return sorted(self.model_usage)

    @property
    def primary_model(self) -> str | None:
        best_model: str | None = None
        best_total = -1
        for model, usage in self.model_usage.items():
            total = usage.tokens.total or 0
            if total > best_total:
                best_model = model
                best_total = total
        if best_model is not None:
            return best_model
        return self.models[0] if self.models else None


@dataclass(slots=True)
class ProviderStatus:
    provider: ProviderName
    status: ProviderSupportLevel
    found_paths: list[Path] = field(default_factory=list)
    ignored_paths: list[Path] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScanFilters:
    providers: set[ProviderName] | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int | None = None
    model: str | None = None
    show_title: bool = False
    show_path: bool = False


@dataclass(slots=True)
class ScanResult:
    statuses: list[ProviderStatus]
    sessions: list[SessionRecord]
    warnings: list[str] = field(default_factory=list)
