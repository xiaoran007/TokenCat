from __future__ import annotations

import json
import os
import sys
from typing import List, Optional

import typer
from rich.console import Console

from tokencat import __version__
from tokencat.dashboard import load_dashboard
from tokencat.core.models import DashboardThemeMode, DashboardUsageGranularity, ProviderName, ScanFilters
from tokencat.core.render import render_dashboard, resolve_dashboard_theme
from tokencat.core.serialize import (
    serialize_daily_records, serialize_filters, serialize_pricing_catalog,
    serialize_pricing_coverage, serialize_session, serialize_status,
)
from tokencat.core.time import local_now, parse_datetime_value
from tokencat.core.updates import check_latest_version

app = typer.Typer(help="TokenCat: local-first, read-only token and usage inspector for AI coding agents.", invoke_without_command=True)
console = Console(highlight=False)

ProviderOption = Optional[List[ProviderName]]


def _emit_json(payload: object) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def build_filters(
    providers: list[ProviderName] | None,
    since: str | None,
    until: str | None,
    limit: int | None,
    model: str | None,
    show_title: bool,
    show_path: bool,
) -> ScanFilters:
    provider_set = set(providers) if providers else None
    try:
        since_value = parse_datetime_value(since, bound="since")
        until_value = parse_datetime_value(until, bound="until")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    return ScanFilters(
        providers=provider_set,
        since=since_value,
        until=until_value,
        limit=limit,
        model=model,
        show_title=show_title,
        show_path=show_path,
    )


@app.callback()
def main(
    ctx: typer.Context,
    providers: ProviderOption = typer.Option(None, "--provider", help="Filter to one or more providers.", case_sensitive=False),
    since: Optional[str] = typer.Option("7d", "--since", help="Relative like 7d/24h or ISO date/datetime."),
    until: Optional[str] = typer.Option(None, "--until", help="Relative like 7d/24h or ISO date/datetime."),
    daily_view: bool = typer.Option(False, "--daily", help="Force daily usage buckets in the terminal dashboard."),
    weekly_view: bool = typer.Option(False, "--weekly", help="Force weekly usage buckets in the terminal dashboard."),
    monthly_view: bool = typer.Option(False, "--monthly", help="Force monthly usage buckets in the terminal dashboard."),
    no_price: bool = typer.Option(False, "--no-price", help="Disable pricing and cost estimation."),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON instead of styled dashboard output."),
    theme: DashboardThemeMode = typer.Option(DashboardThemeMode.AUTO, "--theme", help="Theme for the terminal dashboard: auto, dark, or light."),
) -> None:
    if ctx.invoked_subcommand is None:
        _run_dashboard(
            providers=providers,
            since=since,
            until=until,
            daily_view=daily_view,
            weekly_view=weekly_view,
            monthly_view=monthly_view,
            no_price=no_price,
            json_output=json_output,
            show_recent_sessions=False,
            theme=theme,
        )


@app.command()
def dashboard(
    ctx: typer.Context,
    providers: ProviderOption = typer.Option(None, "--provider", help="Filter to one or more providers.", case_sensitive=False),
    since: Optional[str] = typer.Option("7d", "--since", help="Relative like 7d/24h or ISO date/datetime."),
    until: Optional[str] = typer.Option(None, "--until", help="Relative like 7d/24h or ISO date/datetime."),
    daily_view: bool = typer.Option(False, "--daily", help="Force daily usage buckets in the dashboard."),
    weekly_view: bool = typer.Option(False, "--weekly", help="Force weekly usage buckets in the dashboard."),
    monthly_view: bool = typer.Option(False, "--monthly", help="Force monthly usage buckets in the dashboard."),
    no_price: bool = typer.Option(False, "--no-price", help="Disable pricing and cost estimation."),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON instead of the dashboard."),
    theme: DashboardThemeMode = typer.Option(DashboardThemeMode.AUTO, "--theme", help="Theme for the terminal dashboard: auto, dark, or light."),
) -> None:
    _run_dashboard(
        providers=providers,
        since=since,
        until=until,
        daily_view=daily_view,
        weekly_view=weekly_view,
        monthly_view=monthly_view,
        no_price=no_price,
        json_output=json_output,
        show_recent_sessions=True,
        theme=theme,
    )


def _run_dashboard(
    *,
    providers: list[ProviderName] | None,
    since: str | None,
    until: str | None,
    daily_view: bool,
    weekly_view: bool,
    monthly_view: bool,
    no_price: bool,
    json_output: bool,
    show_recent_sessions: bool,
    theme: DashboardThemeMode,
) -> None:
    filters = build_filters(providers, since, until, limit=None, model=None, show_title=False, show_path=False)
    usage_granularity = _resolve_dashboard_usage_granularity(
        filters,
        daily_view=daily_view,
        weekly_view=weekly_view,
        monthly_view=monthly_view,
    )
    data = load_dashboard(filters, usage_granularity, pricing_enabled=not no_price)
    time_label = _format_window_label(filters)

    payload = {
        "generated_at": local_now().isoformat(),
        "filters": serialize_filters(filters),
        "providers": [serialize_status(status) for status in data.statuses],
        "summary": {
            "overview": data.overview,
            "daily": serialize_daily_records(data.daily),
            "top_models": data.top_models[:8],
            "nodes": data.nodes,
            "recent_sessions": [serialize_session(record, show_title=False, show_path=False) for record in data.sessions],
            "pricing": {
                "catalog": serialize_pricing_catalog(data.catalog),
                "coverage": serialize_pricing_coverage(data.coverage),
            },
        },
        "warnings": data.warnings,
    }
    if json_output:
        _emit_json(payload)
        return

    resolved_theme = resolve_dashboard_theme(theme, os.environ)
    update_notice = check_latest_version(__version__)
    render_dashboard(
        console,
        time_label=time_label,
        statuses=data.statuses,
        overview=data.overview,
        daily=data.usage,
        sessions=data.sessions,
        nodes=data.nodes,
        pricing_catalog=data.catalog,
        pricing_coverage=data.coverage,
        warnings=data.warnings,
        show_recent_sessions=show_recent_sessions,
        usage_granularity=usage_granularity,
        theme=resolved_theme,
        update_notice=update_notice,
    )


def _resolve_dashboard_usage_granularity(
    filters: ScanFilters,
    *,
    daily_view: bool,
    weekly_view: bool,
    monthly_view: bool,
) -> DashboardUsageGranularity:
    explicit_flags = [daily_view, weekly_view, monthly_view]
    if sum(1 for flag in explicit_flags if flag) > 1:
        console.print("Choose at most one of --daily, --weekly, or --monthly.")
        raise typer.Exit(code=2)
    if daily_view:
        return DashboardUsageGranularity.DAILY
    if weekly_view:
        return DashboardUsageGranularity.WEEKLY
    if monthly_view:
        return DashboardUsageGranularity.MONTHLY

    if filters.since is None:
        return DashboardUsageGranularity.DAILY
    window_end = filters.until or local_now()
    window_days = max((window_end - filters.since).total_seconds() / 86400, 0)
    if window_days > 42:
        return DashboardUsageGranularity.MONTHLY
    if window_days > 14:
        return DashboardUsageGranularity.WEEKLY
    return DashboardUsageGranularity.DAILY


def _format_window_label(filters: ScanFilters) -> str:
    start = filters.since.astimezone().date().isoformat() if filters.since is not None else "start"
    end = filters.until.astimezone().date().isoformat() if filters.until is not None else local_now().date().isoformat()
    return f"{start} -> {end}"
