"""Translate native query results into the existing dashboard's presentation data."""
from datetime import datetime
from pathlib import Path
import os

import typer

from tokencat.core.dashboard import DashboardData
from tokencat.core.models import (
    CostEstimate, DailyModelUsageRecord, DailyUsageRecord, DashboardUsageGranularity,
    PricingCatalog, PricingCoverage, ProviderName, ProviderStatus, ProviderSupportLevel,
    SessionRecord, TokenTotals,
)
from tokencat.core.time import _local_timezone, local_now, parse_unix_timestamp
from tokencat_native.engine import Engine

SUPPORTED = {ProviderName.CODEX, ProviderName.CLAUDE, ProviderName.OPENCODE, ProviderName.ANTIGRAVITY}


def configuration(home=None):
    home = home or Path.home()
    claude = os.environ.get("CLAUDE_CONFIG_DIR")
    roots = ([Path(root.strip()).expanduser() for root in claude.split(",") if root.strip()] if claude else
             [Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))).expanduser() / "claude", home / ".claude"])
    return {"home": str(home), "database_path": str(home / ".tokencat-candidate/usage.sqlite3"),
            "pricing_path": None, "codex_root": None, "claude_roots": [str(root) for root in roots],
            "opencode_root": None, "antigravity_roots": []}


def _tokens(summary):
    # The existing view stores reasoning separately and adds it once when displaying output.
    return TokenTotals(input=summary["input_tokens"], cached=summary["cache_read_tokens"],
                       cache_write=summary["cache_write_tokens"], reasoning=summary["reasoning_tokens"],
                       output=summary["output_tokens"] - summary["reasoning_tokens"], total=summary["cost"]["total_tokens"])


def _cost(cost, enabled):
    if not enabled:
        return CostEstimate()
    low, high = cost["min_usd"], cost["max_usd"]
    display = f"${low:,.2f}–${high:,.2f}" if low != high else None
    if cost["unpriced_events"]:
        display = f"Known {display or f'${low:,.2f}'}" if cost["priced_tokens"] else "No price record"
    return CostEstimate(input_cost=cost["input_usd"], cached_input_cost=cost["cache_read_usd"],
                        output_cost=cost["output_usd"], cache_write_cost=cost["cache_write_min_usd"],
                        total_cost=low, max_cost=high, display_cost=display)


def _pricing_status(cost, enabled):
    if not enabled:
        return None
    return "partial" if cost["unpriced_events"] or cost["uncertain_events"] else "priced"


def _model(row, enabled):
    return {"provider": row["provider"], "model": row["label"], "token_totals": _tokens(row["summary"]).to_dict(),
            "estimated_cost": _cost(row["summary"]["cost"], enabled).to_dict(),
            "pricing_status": _pricing_status(row["summary"]["cost"], enabled)}


def _daily(snapshot, zone, granularity, enabled):
    records = []
    for bucket in snapshot["timeline"]:
        summary, details = bucket["summary"], bucket["details"]
        date = datetime.fromtimestamp(bucket["timestamp_ms"] / 1000, zone).date()
        records.append(DailyUsageRecord(
            date=date, label=date.strftime("%Y-%m") if granularity is DashboardUsageGranularity.MONTHLY else date.isoformat(),
            providers={ProviderName(row["provider"]) for row in details["models"]},
            token_totals=_tokens(summary), session_count=details["session_count"],
            estimated_cost=_cost(summary["cost"], enabled),
            priced_tokens=summary["cost"]["priced_tokens"] if enabled else 0,
            total_tokens=summary["cost"]["total_tokens"],
            models=[DailyModelUsageRecord(
                provider=ProviderName(row["provider"]), model=row["label"], token_totals=_tokens(row["summary"]),
                estimated_cost=_cost(row["summary"]["cost"], enabled),
                pricing_status=_pricing_status(row["summary"]["cost"], enabled),
                priced_tokens=row["summary"]["cost"]["priced_tokens"] if enabled else 0,
            ) for row in details["models"]],
        ))
    return records


def adapt(snapshot, daily_snapshot, zone, granularity, *, pricing_enabled):
    summary, cost = snapshot["summary"], snapshot["summary"]["cost"]
    models = sorted((_model(row, pricing_enabled) for row in snapshot["models"]),
                    key=lambda row: (-row["token_totals"]["total"], row["model"]))
    sessions = [SessionRecord(
        provider=ProviderName(row["provider"]), provider_session_id=row["label"], anon_session_id=row["label"],
        started_at=None, updated_at=parse_unix_timestamp(row["summary"]["latest_event_ms"] / 1000)
        if row["summary"]["latest_event_ms"] is not None else None,
        token_totals=_tokens(row["summary"]), primary_model_override=row.get("primary_model"),
        estimated_cost=_cost(row["summary"]["cost"], pricing_enabled),
        pricing_status=_pricing_status(row["summary"]["cost"], pricing_enabled),
    ) for row in snapshot["sessions"] if row["summary"]["event_count"] > 0]
    coverage = PricingCoverage(
        total_tokens=cost["total_tokens"], priced_tokens=cost["priced_tokens"],
        unpriced_tokens=cost["total_tokens"] - cost["priced_tokens"], unknown_models=cost["unknown_models"],
        fallback_priced_tokens=None, priced_model_count=None, unknown_model_tokens=None, unattributed_token_count=None,
        estimated_cost=_cost(cost, True),
    ) if pricing_enabled else None
    detail = (f"coverage {coverage.priced_ratio:.1%}  unpriced {cost['unpriced_events']}  uncertain {cost['uncertain_events']}"
              if coverage else "pricing disabled")
    statuses = [ProviderStatus(provider=ProviderName(row["id"]), status=ProviderSupportLevel.SUPPORTED,
                               reasons=["Usage recorded within the query window."]) for row in snapshot["providers"]]
    report = snapshot["last_scan"]
    warnings = list(report["warnings"]) if report else []
    if report and report["undated_events"]:
        warnings.append(f"{report['undated_events']} undated events ({report['undated_tokens']:,} tokens) are outside time-window totals.")
    if summary["incomplete_events"]:
        warnings.append(f"{summary['incomplete_events']} usage events have incomplete token records.")
    return DashboardData(
        statuses=statuses,
        overview={"session_count": len(sessions), "model_count": sum(row["id"] != "unknown" for row in snapshot["models"]),
                  "token_totals": _tokens(summary).to_dict(), "estimated_cost": _cost(cost, pricing_enabled).to_dict(),
                  "top_models": models[:5], "secondary_metrics": {"provider_count": len(statuses), "detail_text": detail,
                                                                   "pricing_status": _pricing_status(cost, pricing_enabled)}},
        daily=_daily(daily_snapshot, zone, DashboardUsageGranularity.DAILY, pricing_enabled),
        usage=_daily(snapshot, zone, granularity, pricing_enabled), top_models=models, sessions=sessions[:6],
        catalog=PricingCatalog(source=", ".join(snapshot["catalog_sources"]), loaded_at=local_now(), entries=None,
                               refreshed_at=snapshot["catalog_retrieved_at"]) if pricing_enabled else None,
        coverage=coverage, warnings=warnings,
    )


def load_dashboard(filters, granularity, *, pricing_enabled):
    if filters.providers and not filters.providers <= SUPPORTED:
        raise typer.BadParameter("The native candidate supports Codex, Claude Code, OpenCode, and Antigravity only.")
    zone = _local_timezone()
    if zone is None:
        raise typer.BadParameter("Cannot identify the local time zone; set TZ to an IANA time zone.")
    since_ms = int(filters.since.timestamp() * 1000) if filters.since else 0
    # Reuse the CLI's inclusive end bound; native queries use an exclusive millisecond bound.
    until_ms = int(filters.until.timestamp() * 1000) + 1 if filters.until else int(local_now().timestamp() * 1000)
    if since_ms >= until_ms:
        raise typer.BadParameter("Query end must be after start.")
    query = {"since_ms": since_ms, "until_ms": until_ms, "timezone": zone.key,
             "providers": sorted(provider.value for provider in filters.providers) if filters.providers else None,
             "granularity": "day", "show_paths": False, "include_details": True}
    try:
        with Engine(configuration()) as engine:
            engine.scan()
            daily = engine.query(query)
            query["granularity"] = {DashboardUsageGranularity.DAILY: "day", DashboardUsageGranularity.WEEKLY: "week",
                                    DashboardUsageGranularity.MONTHLY: "month"}[granularity]
            snapshot = daily if granularity is DashboardUsageGranularity.DAILY else engine.query(query)
    except (RuntimeError, ValueError, OSError) as exc:
        typer.echo(f"Candidate error: {exc}", err=True)
        raise typer.Exit(1) from exc
    return adapt(snapshot, daily, zone, granularity, pricing_enabled=pricing_enabled)
