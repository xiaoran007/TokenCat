from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from tokencat.core.aggregate import aggregate_models, aggregate_summary
from tokencat.core.models import ProviderName, ProviderStatus, ScanFilters, SessionRecord, TokenTotals
from tokencat.core.serialize import serialize_filters, serialize_session, serialize_status
from tokencat.core.time import local_now, parse_datetime_value
from tokencat.providers.registry import scan_providers

app = typer.Typer(help="TokenCat: local-first, read-only token and usage inspector for AI coding agents.")
console = Console()

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


@app.command()
def doctor(
    json_output: Annotated[bool, typer.Option("--json", help="Emit structured JSON instead of tables.")] = False,
) -> None:
    filters = ScanFilters()
    result = scan_providers(filters)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "filters": serialize_filters(filters),
        "providers": [serialize_status(status) for status in result.statuses],
        "summary": None,
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
            status.provider.value,
            status.status.value,
            "\n".join(str(path) for path in status.found_paths) or "-",
            "\n".join(str(path) for path in status.ignored_paths) or "-",
            "\n".join(status.reasons + status.warnings) or "-",
        )
    console.print(table)


@app.command()
def summary(
    providers: ProviderOption = None,
    since: Annotated[str | None, typer.Option("--since", help="Relative like 7d/24h or ISO date/datetime.")] = None,
    until: Annotated[str | None, typer.Option("--until", help="Relative like 7d/24h or ISO date/datetime.")] = None,
    limit: Annotated[int | None, typer.Option("--limit", min=1, help="Cap matching sessions before aggregation.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit structured JSON instead of tables.")] = False,
) -> None:
    filters = build_filters(providers, since, until, limit, model=None, show_title=False, show_path=False)
    result = scan_providers(filters)
    summary_data = aggregate_summary(result.sessions)
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
    for name, value in _token_rows(summary_data["token_totals"]).items():
        overall.add_row(name, value)
    console.print(overall)

    providers_table = Table(title="By Provider")
    providers_table.add_column("Provider")
    providers_table.add_column("Sessions")
    providers_table.add_column("Models")
    providers_table.add_column("Total Tokens")
    for provider_name, provider_summary in summary_data["providers"].items():
        providers_table.add_row(
            provider_name,
            str(provider_summary["session_count"]),
            str(provider_summary["model_count"]),
            str(provider_summary["token_totals"]["total"] or 0),
        )
    console.print(providers_table)


@app.command()
def sessions(
    providers: ProviderOption = None,
    since: Annotated[str | None, typer.Option("--since", help="Relative like 7d/24h or ISO date/datetime.")] = None,
    until: Annotated[str | None, typer.Option("--until", help="Relative like 7d/24h or ISO date/datetime.")] = None,
    limit: Annotated[int | None, typer.Option("--limit", min=1, help="Maximum number of sessions to show.")] = 50,
    model: Annotated[str | None, typer.Option("--model", help="Only include sessions that used this model.")] = None,
    show_title: Annotated[bool, typer.Option("--show-title", help="Show local session titles when available.")] = False,
    show_path: Annotated[bool, typer.Option("--show-path", help="Show local paths/source refs when available.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit structured JSON instead of tables.")] = False,
) -> None:
    filters = build_filters(providers, since, until, limit, model, show_title, show_path)
    result = scan_providers(filters)
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
    table.add_column("Total Tokens")
    if show_title:
        table.add_column("Title")
    if show_path:
        table.add_column("Path")

    for record in result.sessions:
        row = [
            record.anon_session_id,
            record.provider.value,
            _format_datetime(record.updated_at or record.started_at),
            record.primary_model or "-",
            str(record.token_totals.total or 0),
        ]
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
    since: Annotated[str | None, typer.Option("--since", help="Relative like 7d/24h or ISO date/datetime.")] = None,
    until: Annotated[str | None, typer.Option("--until", help="Relative like 7d/24h or ISO date/datetime.")] = None,
    limit: Annotated[int | None, typer.Option("--limit", min=1, help="Maximum number of rows to show.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit structured JSON instead of tables.")] = False,
) -> None:
    filters = build_filters(providers, since, until, limit=None, model=None, show_title=False, show_path=False)
    result = scan_providers(filters)
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
    table.add_column("Sessions")
    table.add_column("Messages")
    table.add_column("Total Tokens")
    table.add_column("Input")
    table.add_column("Output")
    table.add_column("Cached")
    table.add_column("Reasoning")
    table.add_column("Tool")

    for item in items:
        tokens = item["token_totals"]
        table.add_row(
            item["provider"],
            item["model"],
            str(item["session_count"]),
            str(item["message_count"]),
            str(tokens["total"] or 0),
            str(tokens["input"] or 0),
            str(tokens["output"] or 0),
            str(tokens["cached"] or 0),
            str(tokens["reasoning"] or 0),
            str(tokens["tool"] or 0),
        )
    console.print(table)


def _token_rows(tokens: dict[str, int | None]) -> dict[str, str]:
    return {
        "Input Tokens": str(tokens["input"] or 0),
        "Output Tokens": str(tokens["output"] or 0),
        "Cached Tokens": str(tokens["cached"] or 0),
        "Reasoning Tokens": str(tokens["reasoning"] or 0),
        "Tool Tokens": str(tokens["tool"] or 0),
        "Total Tokens": str(tokens["total"] or 0),
    }


def _format_datetime(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") if value is not None else "-"
