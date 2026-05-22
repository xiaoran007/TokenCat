from __future__ import annotations

import json
import os
from datetime import datetime
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from tokencat import __version__
from tokencat.core.aggregate import aggregate_daily, aggregate_dashboard_usage, aggregate_models, aggregate_nodes, aggregate_summary, build_dashboard_overview
from tokencat.core.models import DashboardThemeMode, DashboardUsageGranularity, PricingCatalog, PricingCoverage, ProviderName, ScanFilters
from tokencat.core.pricing import apply_pricing, load_pricing_catalog, refresh_user_pricing_cache
from tokencat.core.presentation import filter_displayable_model_items, filter_displayable_sessions, provider_display_name
from tokencat.core.render import render_dashboard, render_pricing_summary, resolve_dashboard_theme
from tokencat.core.serialize import (
    serialize_daily_records,
    serialize_filters,
    serialize_pricing_catalog,
    serialize_pricing_coverage,
    serialize_session,
    serialize_status,
)
from tokencat.core.time import local_now, parse_datetime_value
from tokencat.core.updates import check_latest_version
from tokencat.node.client import fetch_remote_node
from tokencat.node.discovery import DiscoveryUnavailable, discover_nodes, register_service
from tokencat.node.identity import load_or_create_identity
from tokencat.node.lan import scan_lan
from tokencat.node.server import serve_forever
from tokencat.node.trust import DEFAULT_TOKEN_ENV, load_trusted_nodes, merge_trusted_nodes, save_trusted_nodes
from tokencat.providers.registry import scan_providers

app = typer.Typer(help="TokenCat: local-first, read-only token and usage inspector for AI coding agents.", invoke_without_command=True)
pricing_app = typer.Typer(help="Inspect and refresh the local pricing catalog.")
app.add_typer(pricing_app, name="pricing")
console = Console(highlight=False)

ProviderOption = Optional[List[ProviderName]]


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
    lan: bool = typer.Option(False, "--lan", help="Include trusted TokenCat nodes discovered on the LAN."),
    lan_timeout: float = typer.Option(2.0, "--lan-timeout", min=0.5, help="Seconds to wait for LAN discovery."),
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
            lan=lan,
            lan_timeout=lan_timeout,
        )


@app.command()
def dashboard(
    providers: ProviderOption = typer.Option(None, "--provider", help="Filter to one or more providers.", case_sensitive=False),
    since: Optional[str] = typer.Option("7d", "--since", help="Relative like 7d/24h or ISO date/datetime."),
    until: Optional[str] = typer.Option(None, "--until", help="Relative like 7d/24h or ISO date/datetime."),
    daily_view: bool = typer.Option(False, "--daily", help="Force daily usage buckets in the dashboard."),
    weekly_view: bool = typer.Option(False, "--weekly", help="Force weekly usage buckets in the dashboard."),
    monthly_view: bool = typer.Option(False, "--monthly", help="Force monthly usage buckets in the dashboard."),
    no_price: bool = typer.Option(False, "--no-price", help="Disable pricing and cost estimation."),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON instead of the dashboard."),
    theme: DashboardThemeMode = typer.Option(DashboardThemeMode.AUTO, "--theme", help="Theme for the terminal dashboard: auto, dark, or light."),
    lan: bool = typer.Option(False, "--lan", help="Include trusted TokenCat nodes discovered on the LAN."),
    lan_timeout: float = typer.Option(2.0, "--lan-timeout", min=0.5, help="Seconds to wait for LAN discovery."),
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
        lan=lan,
        lan_timeout=lan_timeout,
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
    lan: bool,
    lan_timeout: float,
) -> None:
    filters = build_filters(providers, since, until, limit=None, model=None, show_title=False, show_path=False)
    usage_granularity = _resolve_dashboard_usage_granularity(
        filters,
        daily_view=daily_view,
        weekly_view=weekly_view,
        monthly_view=monthly_view,
    )
    result, catalog, coverage = _scan_with_pricing(filters, pricing_enabled=not no_price, lan=lan, lan_timeout=lan_timeout)
    summary_data = aggregate_summary(result.sessions, pricing_coverage=coverage)
    node_items = aggregate_nodes(result.sessions) if lan else []
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
            "nodes": node_items,
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

    resolved_theme = resolve_dashboard_theme(theme, os.environ)
    update_notice = check_latest_version(__version__)
    render_dashboard(
        console,
        time_label=time_label,
        statuses=result.statuses,
        overview=overview,
        daily=dashboard_usage,
        sessions=recent_sessions,
        nodes=node_items,
        pricing_catalog=catalog,
        pricing_coverage=coverage,
        warnings=result.warnings,
        show_recent_sessions=show_recent_sessions,
        usage_granularity=usage_granularity,
        theme=resolved_theme,
        update_notice=update_notice,
    )


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON instead of tables."),
    lan: bool = typer.Option(False, "--lan", help="Include trusted TokenCat nodes discovered on the LAN."),
    lan_timeout: float = typer.Option(2.0, "--lan-timeout", min=0.5, help="Seconds to wait for LAN discovery."),
) -> None:
    filters = ScanFilters()
    result = scan_lan(filters, identity=load_or_create_identity(), discovery_timeout=lan_timeout).result if lan else scan_providers(filters)
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
    providers: ProviderOption = typer.Option(None, "--provider", help="Filter to one or more providers.", case_sensitive=False),
    since: Optional[str] = typer.Option(None, "--since", help="Relative like 7d/24h or ISO date/datetime."),
    until: Optional[str] = typer.Option(None, "--until", help="Relative like 7d/24h or ISO date/datetime."),
    limit: Optional[int] = typer.Option(None, "--limit", min=1, help="Cap matching sessions before aggregation."),
    no_price: bool = typer.Option(False, "--no-price", help="Disable pricing and cost estimation."),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON instead of tables."),
    lan: bool = typer.Option(False, "--lan", help="Include trusted TokenCat nodes discovered on the LAN."),
    lan_timeout: float = typer.Option(2.0, "--lan-timeout", min=0.5, help="Seconds to wait for LAN discovery."),
) -> None:
    filters = build_filters(providers, since, until, limit, model=None, show_title=False, show_path=False)
    result, _, coverage = _scan_with_pricing(filters, pricing_enabled=not no_price, lan=lan, lan_timeout=lan_timeout)
    summary_data = aggregate_summary(result.sessions, pricing_coverage=coverage)
    node_items = aggregate_nodes(result.sessions) if lan else []
    payload = {
        "generated_at": local_now().isoformat(),
        "filters": serialize_filters(filters),
        "providers": [serialize_status(status) for status in result.statuses],
        "summary": summary_data,
        "nodes": node_items,
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

    if lan:
        nodes_table = Table(title="By Node")
        nodes_table.add_column("Node")
        nodes_table.add_column("Sessions")
        nodes_table.add_column("Providers")
        nodes_table.add_column("Models")
        nodes_table.add_column("Total Tokens")
        nodes_table.add_column("Est Cost")
        for item in node_items:
            nodes_table.add_row(
                item["node_name"],
                str(item["session_count"]),
                str(item["provider_count"]),
                str(item["model_count"]),
                _format_tokens(item["token_totals"]["total"]),
                _format_cost(item["estimated_cost"]["total_cost"]),
            )
        console.print(nodes_table)


@app.command()
def daily(
    providers: ProviderOption = typer.Option(None, "--provider", help="Filter to one or more providers.", case_sensitive=False),
    since: Optional[str] = typer.Option("7d", "--since", help="Relative like 7d/24h or ISO date/datetime."),
    until: Optional[str] = typer.Option(None, "--until", help="Relative like 7d/24h or ISO date/datetime."),
    limit: Optional[int] = typer.Option(None, "--limit", min=1, help="Maximum number of rows to show."),
    no_price: bool = typer.Option(False, "--no-price", help="Disable pricing and cost estimation."),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON instead of tables."),
    lan: bool = typer.Option(False, "--lan", help="Include trusted TokenCat nodes discovered on the LAN."),
    lan_timeout: float = typer.Option(2.0, "--lan-timeout", min=0.5, help="Seconds to wait for LAN discovery."),
) -> None:
    filters = build_filters(providers, since, until, limit=None, model=None, show_title=False, show_path=False)
    result, _, _ = _scan_with_pricing(filters, pricing_enabled=not no_price, lan=lan, lan_timeout=lan_timeout)
    items = aggregate_daily(result.sessions)
    if limit is not None:
        items = items[:limit]

    payload = {
        "generated_at": local_now().isoformat(),
        "filters": serialize_filters(filters),
        "providers": [serialize_status(status) for status in result.statuses],
        "items": serialize_daily_records(items),
        "warnings": result.warnings,
    }
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return

    visible_items = [item for item in items if item.token_totals.total or item.models]
    if not visible_items:
        console.print("No daily usage in this window.")
        return

    table = Table(title="TokenCat Daily Usage")
    table.add_column("Date")
    table.add_column("Providers")
    table.add_column("Sessions")
    table.add_column("Total Tokens")
    if not no_price:
        table.add_column("Est Cost", justify="right")
        table.add_column("Coverage", justify="right")
    table.add_column("Top Models")

    for item in visible_items:
        models = ", ".join(
            _daily_model_display(model)
            for model in item.models[:3]
        ) or "-"
        table.add_row(
            item.label or item.date.isoformat(),
            ", ".join(provider_display_name(provider) for provider in sorted(item.providers, key=lambda value: value.value)) or "-",
            str(item.session_count),
            _format_tokens(item.token_totals.total),
            *(
                [
                    _format_cost(item.estimated_cost.total_cost),
                    _format_ratio((item.priced_tokens / item.total_tokens) if item.total_tokens else 0.0),
                ]
                if not no_price
                else []
            ),
            models,
        )
    console.print(table)


@app.command()
def sessions(
    providers: ProviderOption = typer.Option(None, "--provider", help="Filter to one or more providers.", case_sensitive=False),
    since: Optional[str] = typer.Option("7d", "--since", help="Relative like 7d/24h or ISO date/datetime."),
    until: Optional[str] = typer.Option(None, "--until", help="Relative like 7d/24h or ISO date/datetime."),
    limit: Optional[int] = typer.Option(50, "--limit", min=1, help="Maximum number of sessions to show."),
    model: Optional[str] = typer.Option(None, "--model", help="Only include sessions that used this model."),
    show_title: bool = typer.Option(False, "--show-title", help="Show local session titles when available."),
    show_path: bool = typer.Option(False, "--show-path", help="Show local paths/source refs when available."),
    no_price: bool = typer.Option(False, "--no-price", help="Disable pricing and cost estimation."),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON instead of tables."),
    lan: bool = typer.Option(False, "--lan", help="Include trusted TokenCat nodes discovered on the LAN."),
    lan_timeout: float = typer.Option(2.0, "--lan-timeout", min=0.5, help="Seconds to wait for LAN discovery."),
) -> None:
    filters = build_filters(providers, since, until, limit, model, show_title, show_path)
    result, _, _ = _scan_with_pricing(filters, pricing_enabled=not no_price, lan=lan, lan_timeout=lan_timeout)
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
    if lan:
        table.add_column("Node")
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
            record.node_name or "-",
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
        if not lan:
            row = row[1:]
        table.add_row(*row)
    console.print(table)


@app.command()
def models(
    providers: ProviderOption = typer.Option(None, "--provider", help="Filter to one or more providers.", case_sensitive=False),
    since: Optional[str] = typer.Option("7d", "--since", help="Relative like 7d/24h or ISO date/datetime."),
    until: Optional[str] = typer.Option(None, "--until", help="Relative like 7d/24h or ISO date/datetime."),
    limit: Optional[int] = typer.Option(None, "--limit", min=1, help="Maximum number of rows to show."),
    no_price: bool = typer.Option(False, "--no-price", help="Disable pricing and cost estimation."),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON instead of tables."),
    lan: bool = typer.Option(False, "--lan", help="Include trusted TokenCat nodes discovered on the LAN."),
    lan_timeout: float = typer.Option(2.0, "--lan-timeout", min=0.5, help="Seconds to wait for LAN discovery."),
) -> None:
    filters = build_filters(providers, since, until, limit=None, model=None, show_title=False, show_path=False)
    result, _, _ = _scan_with_pricing(filters, pricing_enabled=not no_price, lan=lan, lan_timeout=lan_timeout)
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


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Host interface to bind."),
    port: int = typer.Option(8765, "--port", min=0, help="Port to listen on."),
    lan: bool = typer.Option(False, "--lan", help="Bind to the LAN and advertise via mDNS."),
    token_env: str = typer.Option(DEFAULT_TOKEN_ENV, "--token-env", help="Environment variable containing the bearer token."),
) -> None:
    identity = load_or_create_identity()
    bind_host = "0.0.0.0" if lan and host == "127.0.0.1" else host
    token = os.environ.get(token_env)
    registration = None

    def on_ready(server) -> None:
        nonlocal registration
        actual_port = int(server.server_port)
        console.print(f"TokenCat node {identity.name} listening on http://{bind_host}:{actual_port}")
        if token:
            console.print(f"Snapshot API requires bearer token from ${token_env}.")
        elif lan:
            console.print("Warning: LAN node is running without a bearer token.")
        if lan:
            try:
                registration = register_service(
                    identity=identity,
                    host=bind_host,
                    port=actual_port,
                    auth="token" if token else "none",
                )
                console.print("mDNS service advertised as _tokencat._tcp.local.")
            except DiscoveryUnavailable as exc:
                console.print(str(exc))

    try:
        serve_forever(host=bind_host, port=port, identity=identity, token=token, on_ready=on_ready)
    except KeyboardInterrupt:
        console.print("Stopping TokenCat node.")
    finally:
        if registration is not None:
            registration.close()


@app.command()
def nodes(
    trust: bool = typer.Option(False, "--trust", help="Interactively trust discovered nodes."),
    url: Optional[List[str]] = typer.Option(None, "--url", help="Trust a node by base URL, useful for Docker or networks without mDNS."),
    timeout: float = typer.Option(2.0, "--timeout", min=0.5, help="Seconds to wait for LAN discovery."),
    token_env: str = typer.Option(DEFAULT_TOKEN_ENV, "--token-env", help="Environment variable trusted nodes should use for bearer tokens."),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON instead of a table."),
) -> None:
    identity = load_or_create_identity()
    discovery_warnings: list[str] = []
    try:
        discovered = [node for node in discover_nodes(timeout=timeout) if node.node_id != identity.node_id]
    except DiscoveryUnavailable as exc:
        discovered = []
        discovery_warnings.append(str(exc))
        if not url:
            console.print(str(exc))
            raise typer.Exit(code=2) from exc

    url_nodes, url_warnings = _fetch_url_nodes(url or [], timeout=timeout)
    discovered = _merge_node_endpoints(discovered, url_nodes)
    trusted = load_trusted_nodes()
    trusted_ids = {node.node_id for node in trusted}
    payload = {
        "generated_at": local_now().isoformat(),
        "local_node": identity.to_dict(),
        "warnings": discovery_warnings + url_warnings,
        "nodes": [
            {
                "id": node.node_id,
                "name": node.name,
                "base_url": node.base_url,
                "version": node.version,
                "api_version": node.api_version,
                "auth": node.auth,
                "trusted": node.node_id in trusted_ids,
            }
            for node in discovered
        ],
    }
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return

    _render_nodes_intro(identity.name, len(trusted))
    _render_nodes_table(discovered, trusted_ids)
    for warning in discovery_warnings + url_warnings:
        console.print(f"Warning: {warning}")
    if not trust:
        return
    selected = _prompt_for_node_selection(discovered, trusted_ids)
    if not selected:
        console.print("No nodes selected.")
        return
    token_env_value = _prompt_for_token_env(selected, default=token_env)
    if not Confirm.ask("Save selected nodes to the local trust store?", default=True):
        console.print("Trust store unchanged.")
        return
    updated = merge_trusted_nodes(trusted, selected, token_env=token_env_value)
    save_trusted_nodes(updated)
    console.print(f"Trusted {len(selected)} node(s).")


@pricing_app.command("show")
def pricing_show(
    providers: ProviderOption = typer.Option(None, "--provider", help="Filter to one or more providers.", case_sensitive=False),
    since: Optional[str] = typer.Option(None, "--since", help="Relative like 7d/24h or ISO date/datetime."),
    until: Optional[str] = typer.Option(None, "--until", help="Relative like 7d/24h or ISO date/datetime."),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON instead of tables."),
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
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON instead of tables."),
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


def _scan_with_pricing(
    filters: ScanFilters,
    *,
    pricing_enabled: bool,
    lan: bool = False,
    lan_timeout: float = 2.0,
) -> tuple[object, PricingCatalog | None, PricingCoverage | None]:
    result = scan_lan(filters, identity=load_or_create_identity(), discovery_timeout=lan_timeout).result if lan else scan_providers(filters)
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


def _fetch_url_nodes(urls: list[str], *, timeout: float) -> tuple[list[object], list[str]]:
    nodes: list[object] = []
    warnings: list[str] = []
    for value in urls:
        try:
            nodes.append(fetch_remote_node(value, timeout=timeout))
        except RuntimeError as exc:
            warnings.append(str(exc))
    return nodes, warnings


def _merge_node_endpoints(first: list[object], second: list[object]) -> list[object]:
    by_id = {node.node_id: node for node in first}
    for node in second:
        by_id[node.node_id] = node
    return sorted(by_id.values(), key=lambda item: (item.name.lower(), item.node_id))


def _render_nodes_intro(local_name: str, trusted_count: int) -> None:
    console.print(
        Panel(
            f"Local node: {local_name}\nTrusted nodes: {trusted_count}\nDiscovery: mDNS first, --url as a Docker/VPN fallback",
            title="TokenCat Nodes",
        )
    )


def _render_nodes_table(nodes: list[object], trusted_ids: set[str]) -> None:
    table = Table(title="TokenCat LAN Nodes")
    table.add_column("#", justify="right")
    table.add_column("Name")
    table.add_column("Address")
    table.add_column("Version")
    table.add_column("Auth")
    table.add_column("Trusted")
    for index, node in enumerate(nodes, start=1):
        table.add_row(
            str(index),
            node.name,
            node.base_url,
            node.version or "-",
            node.auth,
            "yes" if node.node_id in trusted_ids else "no",
        )
    if not nodes:
        table.add_row("-", "No nodes discovered", "-", "-", "-", "-")
    console.print(table)


def _prompt_for_node_selection(nodes: list[object], trusted_ids: set[str]) -> list[object]:
    if not nodes:
        return []
    untrusted = [node for node in nodes if node.node_id not in trusted_ids]
    default = "all" if untrusted else ""
    answer = Prompt.ask("Trust which nodes? Use numbers separated by commas, or 'all'", default=default)
    normalized = answer.strip().lower()
    if not normalized:
        return []
    if normalized in {"a", "all"}:
        return untrusted or nodes
    selected: list[object] = []
    for part in normalized.split(","):
        try:
            index = int(part.strip())
        except ValueError:
            continue
        if 1 <= index <= len(nodes):
            selected.append(nodes[index - 1])
    return selected


def _prompt_for_token_env(nodes: list[object], *, default: str) -> str | None:
    needs_token = any(node.auth == "token" for node in nodes)
    if not needs_token and not Confirm.ask("Use a bearer token environment variable for these nodes?", default=False):
        return None
    token_env = Prompt.ask("Token environment variable", default=default).strip()
    if token_env and token_env not in os.environ:
        console.print(f"Warning: ${token_env} is not set in this shell.")
    return token_env or None


def _token_rows(tokens: dict[str, int | None]) -> dict[str, str]:
    return {
        "Input Tokens": _format_tokens(tokens["input"]),
        "Output Tokens": _format_tokens((tokens["output"] or 0) + (tokens["reasoning"] or 0)),
        "Cached Tokens": _format_tokens(tokens["cached"]),
        "Tool Tokens": _format_tokens(tokens["tool"]),
        "Total Tokens": _format_tokens(tokens["total"]),
    }


def _daily_model_display(model) -> str:
    label = f"{model.model} ({provider_display_name(model.provider)})"
    nodes = sorted(getattr(model, "node_names", set()) or [])
    if not nodes:
        return label
    if len(nodes) == 1:
        return f"{label} @ {nodes[0]}"
    return f"{label} @ {nodes[0]} +{len(nodes) - 1}"


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
