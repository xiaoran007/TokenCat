from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
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

    def known_total(self) -> int:
        return sum(value or 0 for value in (self.input, self.output, self.cached, self.reasoning, self.tool))


@dataclass(slots=True)
class CostEstimate:
    input_cost: float = 0.0
    cached_input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    currency: str = "USD"

    def add(self, other: "CostEstimate") -> None:
        self.input_cost += other.input_cost
        self.cached_input_cost += other.cached_input_cost
        self.output_cost += other.output_cost
        self.total_cost += other.total_cost

    def to_dict(self) -> dict[str, float | str]:
        return {
            "input_cost": round(self.input_cost, 6),
            "cached_input_cost": round(self.cached_input_cost, 6),
            "output_cost": round(self.output_cost, 6),
            "total_cost": round(self.total_cost, 6),
            "currency": self.currency,
        }


@dataclass(slots=True)
class ModelUsage:
    model: str
    tokens: TokenTotals = field(default_factory=TokenTotals)
    message_count: int = 0
    estimated_cost: CostEstimate | None = None
    attribution_status: str | None = None
    pricing_status: str | None = None
    pricing_model: str | None = None
    is_fallback_model: bool = False

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
    estimated_cost: CostEstimate | None = None
    attribution_status: str | None = None
    pricing_status: str | None = None
    pricing_model: str | None = None
    is_fallback_model: bool = False

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


@dataclass(slots=True)
class PricingEntry:
    provider: ProviderName
    model: str
    input_per_1m: float
    output_per_1m: float
    cached_input_per_1m: float | None
    currency: str
    effective_date: str
    source_url: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider.value,
            "model": self.model,
            "input_per_1m": self.input_per_1m,
            "output_per_1m": self.output_per_1m,
            "cached_input_per_1m": self.cached_input_per_1m,
            "currency": self.currency,
            "effective_date": self.effective_date,
            "source_url": self.source_url,
            "notes": self.notes,
        }


@dataclass(slots=True)
class PricingCatalog:
    source: str
    loaded_at: datetime
    entries: dict[tuple[ProviderName, str], PricingEntry]
    source_url: str | None = None
    refreshed_at: str | None = None
    cache_path: Path | None = None

    @property
    def model_count(self) -> int:
        return len(self.entries)


@dataclass(slots=True)
class PricingCoverage:
    total_tokens: int = 0
    priced_tokens: int = 0
    fallback_priced_tokens: int = 0
    unpriced_tokens: int = 0
    priced_model_count: int = 0
    unknown_models: list[str] = field(default_factory=list)
    unknown_model_tokens: int = 0
    unattributed_token_count: int = 0
    estimated_cost: CostEstimate = field(default_factory=CostEstimate)

    @property
    def priced_ratio(self) -> float:
        if self.total_tokens == 0:
            return 0.0
        return self.priced_tokens / self.total_tokens

    def to_dict(self) -> dict[str, object]:
        return {
            "total_tokens": self.total_tokens,
            "priced_tokens": self.priced_tokens,
            "fallback_priced_tokens": self.fallback_priced_tokens,
            "unpriced_tokens": self.unpriced_tokens,
            "priced_ratio": round(self.priced_ratio, 4),
            "priced_model_count": self.priced_model_count,
            "unknown_models": self.unknown_models,
            "unknown_model_tokens": self.unknown_model_tokens,
            "unattributed_token_count": self.unattributed_token_count,
            "estimated_cost": self.estimated_cost.to_dict(),
        }


@dataclass(slots=True)
class DailyModelUsageRecord:
    provider: ProviderName
    model: str
    token_totals: TokenTotals = field(default_factory=TokenTotals.zero)
    estimated_cost: CostEstimate = field(default_factory=CostEstimate)
    session_count: int = 0
    priced_tokens: int = 0
    attribution_status: str | None = None
    pricing_status: str | None = None

    def to_dict(self) -> dict[str, object]:
        total_tokens = self.token_totals.total or 0
        return {
            "provider": self.provider.value,
            "model": self.model,
            "session_count": self.session_count,
            "token_totals": self.token_totals.to_dict(),
            "estimated_cost": self.estimated_cost.to_dict(),
            "priced_ratio": round((self.priced_tokens / total_tokens), 4) if total_tokens else 0.0,
            "attribution_status": self.attribution_status,
            "pricing_status": self.pricing_status,
        }


@dataclass(slots=True)
class DailyUsageRecord:
    date: date
    providers: set[ProviderName] = field(default_factory=set)
    token_totals: TokenTotals = field(default_factory=TokenTotals.zero)
    session_count: int = 0
    estimated_cost: CostEstimate = field(default_factory=CostEstimate)
    priced_tokens: int = 0
    total_tokens: int = 0
    models: list[DailyModelUsageRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "date": self.date.isoformat(),
            "providers": sorted(provider.value for provider in self.providers),
            "session_count": self.session_count,
            "token_totals": self.token_totals.to_dict(),
            "estimated_cost": self.estimated_cost.to_dict(),
            "priced_ratio": round((self.priced_tokens / self.total_tokens), 4) if self.total_tokens else 0.0,
            "models": [model.to_dict() for model in self.models],
        }
