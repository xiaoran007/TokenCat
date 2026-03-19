from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from tokencat.core.aggregate import aggregate_daily, aggregate_dashboard_usage, aggregate_models, aggregate_summary, build_dashboard_overview
from tokencat.core.models import DashboardUsageGranularity, PricingCatalog, PricingCoverage, ProviderName, ScanFilters
from tokencat.core.pricing import apply_pricing, load_pricing_catalog, refresh_user_pricing_cache
from tokencat.core.presentation import filter_displayable_model_items, filter_displayable_sessions, provider_display_name
from tokencat.core.render import render_dashboard, render_pricing_summary
from tokencat.core.serialize import (
    serialize_daily_records,
    serialize_filters,
    serialize_pricing_catalog,
    serialize_pricing_coverage,
    serialize_session,
    serialize_status,
)
from tokencat.core.time import local_now, parse_datetime_value
from tokencat.providers.registry import scan_providers

app = typer.Typer(help="TokenCat: local-first, read-only token and usage inspector for AI coding agents.", invoke_without_command=True)
pricing_app = typer.Typer(help="Inspect and refresh the local pricing catalog.")
app.add_typer(pricing_app, name="pricing")
console = Console(highlight=False)

ProviderOption = Annotated[
    list[ProviderName] | None,
    typer.Option(
        "--provider",
        help="Filter to one or more providers.",
        case_sensitive=False,
    ),
]


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
    providers: ProviderOption = None,
    since: Annotated[str | None, typer.Option("--since", help="Relative like 7d/24h or ISO date/datetime.")] = "7d",
    until: Annotated[str | None, typer.Option("--until", help="Relative like 7d/24h or ISO date/datetime.")] = None,
    daily_view: Annotated[bool, typer.Option("--daily", help="Force daily usage buckets in the terminal dashboard.")] = False,
    weekly_view: Annotated[bool, typer.Option("--weekly", help="Force weekly usage buckets in the terminal dashboard.")] = False,
    monthly_view: Annotated[bool, typer.Option("--monthly", help="Force monthly usage buckets in the terminal dashboard.")] = False,
    no_price: Annotated[bool, typer.Option("--no-price", help="Disable pricing and cost estimation.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit structured JSON instead of styled dashboard output.")] = False,
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
        )


@app.command()
def dashboard(
    providers: ProviderOption = None,
    since: Annotated[str | None, typer.Option("--since", help="Relative like 7d/24h or ISO date/datetime.")] = "7d",
    until: Annotated[str | None, typer.Option("--until", help="Relative like 7d/24h or ISO date/datetime.")] = None,
    daily_view: Annotated[bool, typer.Option("--daily", help="Force daily usage buckets in the dashboard.")] = False,
    weekly_view: Annotated[bool, typer.Option("--weekly", help="Force weekly usage buckets in the dashboard.")] = False,
    monthly_view: Annotated[bool, typer.Option("--monthly", help="Force monthly usage buckets in the dashboard.")] = False,
    no_price: Annotated[bool, typer.Option("--no-price", help="Disable pricing and cost estimation.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit structured JSON instead of the dashboard.")] = False,
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
) -> None:
    filters = build_filters(providers, since, until, limit=None, model=None, show_title=False, show_path=False)
    usage_granularity = _resolve_dashboard_usage_granularity(
        filters,
        daily_view=daily_view,
        weekly_view=weekly_view,
        monthly_view=monthly_view,
    )
    result, catalog, coverage = _scan_with_pricing(filters, pricing_enabled=not no_price)
    summary_data = aggregate_summary(result.sessions, pricing_coverage=coverage)
    daily = aggregate_daily(result.sessions)
    dashboard_usage = aggregate_dashboard_usage(result.sessions, usage_granularity)
    top_models = aggregate_models(result.sessions)
    overview = build_dashboard_overview(summary_data, top_models, result.statuses)
    recent_sessions = filter_displayable_sessions(result.sessions)[:6]
    time_label = _format_window_label(filters)

    payload = {
        "generated_at": local_now().isoformat(),
        "filters": serialize_filters(filters),
        "providers": [serialize_status(status) for status in result.statuses],
        "summary": {
            "overview": overview,
            "daily": serialize_daily_records(daily),
            "top_models": top_models[:8],
            "recent_sessions": [serialize_session(record, show_title=False, show_path=False) for record in recent_sessions],
            "pricing": {
                "catalog": serialize_pricing_catalog(catalog),
                "coverage": serialize_pricing_coverage(coverage),
            },
        },
        "warnings": result.warnings,
    }
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return

    render_dashboard(
        console,
        time_label=time_label,
        statuses=result.statuses,
        overview=overview,
        daily=dashboard_usage,
        sessions=recent_sessions,
        pricing_catalog=catalog,
        pricing_coverage=coverage,
        warnings=result.warnings,
        show_recent_sessions=show_recent_sessions,
        usage_granularity=usage_granularity,
    )


@app.command()
def doctor(
    json_output: Annotated[bool, typer.Option("--json", help="Emit structured JSON instead of tables.")] = False,
) -> None:
    filters = ScanFilters()
    result = scan_providers(filters)
    catalog = load_pricing_catalog()
    pricing_summary = {
        "catalog": serialize_pricing_catalog(catalog),
    }
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "filters": serialize_filters(filters),
        "providers": [serialize_status(status) for status in result.statuses],
        "summary": pricing_summary,
        "warnings": result.warnings,
    }
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return

    table = Table(title="TokenCat Doctor")
    table.add_column("Provider")
    table.add_column("Status")
    table.add_column("Found Paths")
    table.add_column("Ignored Paths")
    table.add_column("Reasons")
    for status in result.statuses:
        table.add_row(
            provider_display_name(status.provider),
            status.status.value,
            "\n".join(str(path) for path in status.found_paths) or "-",
            "\n".join(str(path) for path in status.ignored_paths) or "-",
            "\n".join(status.reasons + status.warnings) or "-",
        )
    console.print(table)
    render_pricing_summary(console, catalog=catalog, coverage=None, unknown_models=[])


@app.command()
def summary(
    providers: ProviderOption = None,
    since: Annotated[str | None, typer.Option("--since", help="Relative like 7d/24h or ISO date/datetime.")] = None,
    until: Annotated[str | None, typer.Option("--until", help="Relative like 7d/24h or ISO date/datetime.")] = None,
    limit: Annotated[int | None, typer.Option("--limit", min=1, help="Cap matching sessions before aggregation.")] = None,
    no_price: Annotated[bool, typer.Option("--no-price", help="Disable pricing and cost estimation.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit structured JSON instead of tables.")] = False,
) -> None:
    filters = build_filters(providers, since, until, limit, model=None, show_title=False, show_path=False)
    result, _, coverage = _scan_with_pricing(filters, pricing_enabled=not no_price)
    summary_data = aggregate_summary(result.sessions, pricing_coverage=coverage)
    payload = {
        "generated_at": local_now().isoformat(),
        "filters": serialize_filters(filters),
        "providers": [serialize_status(status) for status in result.statuses],
        "summary": summary_data,
        "warnings": result.warnings,
    }
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return

    overall = Table(title="TokenCat Summary")
    overall.add_column("Metric")
    overall.add_column("Value")
    overall.add_row("Sessions", str(summary_data["session_count"]))
    overall.add_row("Models", str(summary_data["model_count"]))
    overall.add_row("Estimated API Cost", _format_cost(summary_data["estimated_cost"]["total_cost"]))
    if summary_data.get("pricing_coverage"):
        overall.add_row("Priced Coverage", _format_ratio(summary_data["pricing_coverage"]["priced_ratio"]))
        overall.add_row("Unknown Models", ", ".join(summary_data["pricing_coverage"]["unknown_models"]) or "-")
    for name, value in _token_rows(summary_data["token_totals"]).items():
        overall.add_row(name, value)
    console.print(overall)

    providers_table = Table(title="By Provider")
    providers_table.add_column("Provider")
    providers_table.add_column("Sessions")
    providers_table.add_column("Models")
    providers_table.add_column("Total Tokens")
    providers_table.add_column("Est Cost")
    for provider_name, provider_summary in summary_data["providers"].items():
        providers_table.add_row(
            provider_display_name(provider_name),
            str(provider_summary["session_count"]),
            str(provider_summary["model_count"]),
            _format_tokens(provider_summary["token_totals"]["total"]),
            _format_cost(provider_summary["estimated_cost"]["total_cost"]),
        )
    console.print(providers_table)


@app.command()
def sessions(
    providers: ProviderOption = None,
    since: Annotated[str | None, typer.Option("--since", help="Relative like 7d/24h or ISO date/datetime.")] = "7d",
    until: Annotated[str | None, typer.Option("--until", help="Relative like 7d/24h or ISO date/datetime.")] = None,
    limit: Annotated[int | None, typer.Option("--limit", min=1, help="Maximum number of sessions to show.")] = 50,
    model: Annotated[str | None, typer.Option("--model", help="Only include sessions that used this model.")] = None,
    show_title: Annotated[bool, typer.Option("--show-title", help="Show local session titles when available.")] = False,
    show_path: Annotated[bool, typer.Option("--show-path", help="Show local paths/source refs when available.")] = False,
    no_price: Annotated[bool, typer.Option("--no-price", help="Disable pricing and cost estimation.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit structured JSON instead of tables.")] = False,
) -> None:
    filters = build_filters(providers, since, until, limit, model, show_title, show_path)
    result, _, _ = _scan_with_pricing(filters, pricing_enabled=not no_price)
    payload = {
        "generated_at": local_now().isoformat(),
        "filters": serialize_filters(filters),
        "providers": [serialize_status(status) for status in result.statuses],
        "items": [serialize_session(record, show_title=show_title, show_path=show_path) for record in result.sessions],
        "warnings": result.warnings,
    }
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return

    table = Table(title="TokenCat Sessions")
    table.add_column("Anon ID")
    table.add_column("Provider")
    table.add_column("Updated")
    table.add_column("Primary Model")
    table.add_column("Attr")
    table.add_column("Total Tokens")
    if not no_price:
        table.add_column("Est Cost", justify="right")
        table.add_column("Pricing")
    if show_title:
        table.add_column("Title")
    if show_path:
        table.add_column("Path")

    visible_sessions = filter_displayable_sessions(result.sessions)
    if not visible_sessions:
        console.print("No sessions in this window.")
        return

    for record in visible_sessions:
        row = [
            record.anon_session_id,
            provider_display_name(record.provider),
            _format_datetime(record.updated_at or record.started_at),
            record.primary_model or "-",
            record.attribution_status or "-",
            _format_tokens(record.token_totals.total),
        ]
        if not no_price:
            row.append(_format_cost(record.estimated_cost.total_cost if record.estimated_cost is not None else 0.0))
            row.append(record.pricing_status or "-")
        if show_title:
            row.append(record.title or "-")
        if show_path:
            path_value = record.cwd or (str(record.source_refs[0]) if record.source_refs else "-")
            row.append(path_value)
        table.add_row(*row)
    console.print(table)


@app.command()
def models(
    providers: ProviderOption = None,
    since: Annotated[str | None, typer.Option("--since", help="Relative like 7d/24h or ISO date/datetime.")] = "7d",
    until: Annotated[str | None, typer.Option("--until", help="Relative like 7d/24h or ISO date/datetime.")] = None,
    limit: Annotated[int | None, typer.Option("--limit", min=1, help="Maximum number of rows to show.")] = None,
    no_price: Annotated[bool, typer.Option("--no-price", help="Disable pricing and cost estimation.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit structured JSON instead of tables.")] = False,
) -> None:
    filters = build_filters(providers, since, until, limit=None, model=None, show_title=False, show_path=False)
    result, _, _ = _scan_with_pricing(filters, pricing_enabled=not no_price)
    items = aggregate_models(result.sessions)
    if limit is not None:
        items = items[:limit]
    payload = {
        "generated_at": local_now().isoformat(),
        "filters": serialize_filters(filters),
        "providers": [serialize_status(status) for status in result.statuses],
        "items": items,
        "warnings": result.warnings,
    }
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return

    table = Table(title="TokenCat Models")
    table.add_column("Provider")
    table.add_column("Model")
    table.add_column("Attr")
    table.add_column("Sessions")
    table.add_column("Messages")
    table.add_column("Total Tokens")
    table.add_column("Input")
    table.add_column("Output")
    table.add_column("Cached")
    if not no_price:
        table.add_column("Est Cost", justify="right")
        table.add_column("Coverage", justify="right")

    visible_items = filter_displayable_model_items(items)
    if not visible_items:
        console.print("No model usage in this window.")
        return

    for item in visible_items:
        tokens = item["token_totals"]
        row = [
            provider_display_name(item["provider"]),
            item["model"],
            item.get("attribution_status") or "-",
            str(item["session_count"]),
            str(item["message_count"]),
            _format_tokens(tokens["total"]),
            _format_tokens(tokens["input"]),
            _format_tokens((tokens["output"] or 0) + (tokens["reasoning"] or 0)),
            _format_tokens(tokens["cached"]),
        ]
        if not no_price:
            estimated = item.get("estimated_cost") or {}
            row.append(_format_cost(estimated.get("total_cost", 0.0)))
            row.append(_format_ratio(item.get("priced_token_coverage", 0.0)))
        table.add_row(*row)
    console.print(table)


@pricing_app.command("show")
def pricing_show(
    providers: ProviderOption = None,
    since: Annotated[str | None, typer.Option("--since", help="Relative like 7d/24h or ISO date/datetime.")] = None,
    until: Annotated[str | None, typer.Option("--until", help="Relative like 7d/24h or ISO date/datetime.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit structured JSON instead of tables.")] = False,
) -> None:
    filters = build_filters(providers, since, until, limit=None, model=None, show_title=False, show_path=False)
    result, catalog, coverage = _scan_with_pricing(filters, pricing_enabled=True)
    unknown = coverage.unknown_models if coverage is not None else []
    payload = {
        "generated_at": local_now().isoformat(),
        "filters": serialize_filters(filters),
        "providers": [serialize_status(status) for status in result.statuses],
        "summary": {
            "pricing": {
                "catalog": serialize_pricing_catalog(catalog),
                "coverage": serialize_pricing_coverage(coverage),
                "unknown_models": unknown,
            }
        },
        "warnings": result.warnings,
    }
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    render_pricing_summary(console, catalog=catalog, coverage=coverage, unknown_models=unknown)


@pricing_app.command("refresh")
def pricing_refresh(
    json_output: Annotated[bool, typer.Option("--json", help="Emit structured JSON instead of tables.")] = False,
) -> None:
    warnings: list[str] = []
    try:
        catalog = refresh_user_pricing_cache()
    except Exception as exc:  # pragma: no cover - exercised in tests by function patching
        catalog = load_pricing_catalog()
        warnings.append(str(exc))

    payload = {
        "generated_at": local_now().isoformat(),
        "filters": serialize_filters(ScanFilters()),
        "providers": [],
        "summary": {
            "pricing": {
                "catalog": serialize_pricing_catalog(catalog),
                "coverage": None,
                "unknown_models": [],
            }
        },
        "warnings": warnings,
    }
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    render_pricing_summary(console, catalog=catalog, coverage=None, unknown_models=[])
    if warnings:
        console.print("\n".join(warnings))


def _scan_with_pricing(filters: ScanFilters, *, pricing_enabled: bool) -> tuple[object, PricingCatalog | None, PricingCoverage | None]:
    result = scan_providers(filters)
    if not pricing_enabled:
        return result, None, None
    catalog = load_pricing_catalog()
    coverage = apply_pricing(result.sessions, catalog)
    return result, catalog, coverage


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


def _token_rows(tokens: dict[str, int | None]) -> dict[str, str]:
    return {
        "Input Tokens": _format_tokens(tokens["input"]),
        "Output Tokens": _format_tokens((tokens["output"] or 0) + (tokens["reasoning"] or 0)),
        "Cached Tokens": _format_tokens(tokens["cached"]),
        "Tool Tokens": _format_tokens(tokens["tool"]),
        "Total Tokens": _format_tokens(tokens["total"]),
    }


def _format_datetime(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") if value is not None else "-"


def _format_cost(value: float | None) -> str:
    return f"${(value or 0.0):,.2f}"


def _format_ratio(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_window_label(filters: ScanFilters) -> str:
    start = filters.since.astimezone().date().isoformat() if filters.since is not None else "start"
    end = filters.until.astimezone().date().isoformat() if filters.until is not None else local_now().date().isoformat()
    return f"{start} -> {end}"


def _format_tokens(value: int | None) -> str:
    number = float(value or 0)
    abs_number = abs(number)
    if abs_number >= 1_000_000_000:
        return f"{int(number):,} ({number / 1_000_000_000:.1f}B)"
    if abs_number >= 1_000_000:
        return f"{int(number):,} ({number / 1_000_000:.1f}M)"
    if abs_number >= 1_000:
        return f"{int(number):,} ({number / 1_000:.1f}K)"
    return f"{int(number):,}"
