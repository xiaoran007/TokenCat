from __future__ import annotations

from tokencat.core.aggregate import aggregate_dashboard_usage, aggregate_models, aggregate_summary, build_dashboard_overview
from tokencat.core.models import DashboardUsageGranularity, PricingCatalog, ProviderStatus, ScanFilters
from tokencat.core.pricing import apply_pricing, load_pricing_catalog
from tokencat.core.serialize import (
    serialize_datetime,
    serialize_filters,
    serialize_pricing_coverage,
)
from tokencat.core.time import local_now
from tokencat.providers.registry import scan_providers

SNAPSHOT_SCHEMA_VERSION = 1


def build_snapshot(
    filters: ScanFilters,
    *,
    pricing_enabled: bool,
    usage_granularity: DashboardUsageGranularity,
) -> dict[str, object]:
    result = scan_providers(filters)
    catalog = None
    coverage = None
    if pricing_enabled:
        catalog = load_pricing_catalog()
        coverage = apply_pricing(result.sessions, catalog)

    summary_data = aggregate_summary(result.sessions, pricing_coverage=coverage)
    dashboard_usage = aggregate_dashboard_usage(result.sessions, usage_granularity)
    top_models = aggregate_models(result.sessions)
    overview = build_dashboard_overview(summary_data, top_models, result.statuses)

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": local_now().isoformat(),
        "filters": serialize_filters(filters),
        "providers": [_serialize_snapshot_status(status) for status in result.statuses],
        "overview": overview,
        "usage": {
            "granularity": usage_granularity.value,
            "records": [record.to_dict() for record in dashboard_usage],
        },
        "top_models": top_models[:8],
        "pricing": {
            "catalog": _serialize_snapshot_catalog(catalog),
            "coverage": serialize_pricing_coverage(coverage),
        },
        "warnings": result.warnings,
    }


def _serialize_snapshot_status(status: ProviderStatus) -> dict[str, object]:
    return {
        "provider": status.provider.value,
        "status": status.status.value,
        "reasons": status.reasons,
        "warnings": status.warnings,
    }


def _serialize_snapshot_catalog(catalog: PricingCatalog | None) -> dict[str, object] | None:
    if catalog is None:
        return None
    return {
        "source": catalog.source,
        "loaded_at": serialize_datetime(catalog.loaded_at),
        "source_url": catalog.source_url,
        "refreshed_at": catalog.refreshed_at,
        "model_count": catalog.model_count,
    }
