from __future__ import annotations

from dataclasses import dataclass, field

from tokencat.core.models import DailyUsageRecord, PricingCatalog, PricingCoverage, ProviderStatus, SessionRecord


@dataclass
class DashboardData:
    statuses: list[ProviderStatus]
    overview: dict
    daily: list[DailyUsageRecord]
    usage: list[DailyUsageRecord]
    top_models: list[dict]
    sessions: list[SessionRecord]
    catalog: PricingCatalog | None
    coverage: PricingCoverage | None
    warnings: list[str]
    nodes: list[dict] = field(default_factory=list)
