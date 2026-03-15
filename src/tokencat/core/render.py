from __future__ import annotations

from rich import box
from rich.columns import Columns
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from tokencat.core.models import DailyUsageRecord, PricingCatalog, PricingCoverage, ProviderStatus, SessionRecord

ACCENT = "#d7ba7d"
MUTED = "#9ba1a6"
COOL = "#89dceb"
SUCCESS = "#a6e3a1"
WARN = "#f9e2af"
ERROR = "#f38ba8"


def render_dashboard(
    console: Console,
    *,
    time_label: str,
    statuses: list[ProviderStatus],
    summary: dict[str, object],
    daily: list[DailyUsageRecord],
    top_models: list[dict[str, object]],
    sessions: list[SessionRecord],
    pricing_catalog: PricingCatalog | None,
    pricing_coverage: PricingCoverage | None,
    warnings: list[str],
) -> None:
    renderables = [
        _brand_panel(time_label, statuses, pricing_catalog, pricing_coverage),
        Columns(
            [
                _metric_card("Sessions", str(summary["session_count"]), "Local sessions in range"),
                _metric_card("Total Tokens", _format_int(summary["token_totals"]["total"]), "Across supported providers"),
                _metric_card("Est Cost", _format_cost(summary["estimated_cost"]["total_cost"]), "Equivalent API reference"),
                _metric_card("Coverage", _format_ratio((summary.get("pricing_coverage") or {}).get("priced_ratio", 0.0)), "Priced token share"),
                _metric_card("Models", str(summary["model_count"]), "Unique models seen"),
                _metric_card("Providers", str(len([status for status in statuses if status.status.value == "supported"])), "Supported local sources"),
            ],
            equal=True,
            expand=True,
        ),
        Rule(style=MUTED),
        _daily_table(daily),
        Columns(
            [
                Panel(_top_models_table(top_models[:6]), title="Top Models", border_style=COOL, box=box.ROUNDED),
                Panel(_recent_sessions_table(sessions[:6]), title="Recent Sessions", border_style=ACCENT, box=box.ROUNDED),
            ],
            expand=True,
        ),
    ]
    if warnings:
        warning_text = Text("\n".join(f"- {warning}" for warning in warnings), style=WARN)
        renderables.append(Panel(warning_text, title="Warnings", border_style=WARN, box=box.ROUNDED))
    console.print(Group(*renderables))


def render_pricing_summary(console: Console, *, catalog: PricingCatalog | None, coverage: PricingCoverage | None, unknown_models: list[str]) -> None:
    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("Metric", style=ACCENT)
    table.add_column("Value", justify="right")
    if catalog is not None:
        table.add_row("Catalog source", catalog.source)
        table.add_row("Loaded at", catalog.loaded_at.isoformat(timespec="seconds"))
        table.add_row("Catalog models", str(catalog.model_count))
        table.add_row("Cache path", str(catalog.cache_path or "-"))
    if coverage is not None:
        table.add_row("Priced tokens", _format_int(coverage.priced_tokens))
        table.add_row("Fallback-priced", _format_int(coverage.fallback_priced_tokens))
        table.add_row("Unknown-model", _format_int(coverage.unknown_model_tokens))
        table.add_row("Unattributed", _format_int(coverage.unattributed_token_count))
        table.add_row("Unpriced tokens", _format_int(coverage.unpriced_tokens))
        table.add_row("Coverage", _format_ratio(coverage.priced_ratio))
        table.add_row("Estimated cost", _format_cost(coverage.estimated_cost.total_cost))
    table.add_row("Unknown models", ", ".join(unknown_models) if unknown_models else "-")
    console.print(Panel(table, title="Pricing", border_style=COOL, box=box.ROUNDED))


def _brand_panel(time_label: str, statuses: list[ProviderStatus], pricing_catalog: PricingCatalog | None, pricing_coverage: PricingCoverage | None) -> Panel:
    header = Text()
    header.append("tokencat", style=f"bold {ACCENT}")
    header.append("  local usage cockpit", style=MUTED)
    header.append(f"\nwindow: {time_label}", style=COOL)

    status_line = Text()
    for index, status in enumerate(statuses):
        if index:
            status_line.append("  ")
        color = SUCCESS if status.status.value == "supported" else WARN if status.status.value == "partial" else ERROR if status.status.value == "unsupported" else MUTED
        status_line.append("● ", style=color)
        status_line.append(f"{status.provider.value}:{status.status.value}", style=color)

    footer = Text()
    if pricing_catalog is not None:
        footer.append(f"pricing: {pricing_catalog.source}", style=ACCENT)
        if pricing_catalog.refreshed_at:
            footer.append(f"  refreshed {pricing_catalog.refreshed_at}", style=MUTED)
    if pricing_coverage is not None and pricing_coverage.unknown_models:
        footer.append(f"\nunknown pricing: {', '.join(pricing_coverage.unknown_models)}", style=WARN)
    if pricing_coverage is not None and pricing_coverage.unattributed_token_count:
        footer.append(f"\nunattributed tokens: {_format_int(pricing_coverage.unattributed_token_count)}", style=WARN)

    return Panel(Group(header, status_line, footer), border_style=ACCENT, box=box.ROUNDED)


def _metric_card(label: str, value: str, subtitle: str) -> Panel:
    text = Text()
    text.append(f"{value}\n", style=f"bold {ACCENT}")
    text.append(label, style=COOL)
    text.append(f"\n{subtitle}", style=MUTED)
    return Panel(text, border_style=MUTED, box=box.ROUNDED, padding=(1, 2))


def _daily_table(records: list[DailyUsageRecord]) -> Table:
    table = Table(title="Daily Usage", box=box.SIMPLE_HEAVY, border_style=MUTED, expand=True)
    table.add_column("Date", style=COOL)
    table.add_column("Providers / Models", style=ACCENT)
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Cached", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Est Cost", justify="right")
    for record in records:
        providers = "+".join(sorted(provider.value for provider in record.providers))
        model_summary = f"{len(record.models)} models"
        table.add_row(
            record.date.isoformat(),
            f"{providers}\n{model_summary}",
            _format_int(record.token_totals.input),
            _format_int((record.token_totals.output or 0) + (record.token_totals.reasoning or 0)),
            _format_int(record.token_totals.cached),
            _format_int(record.token_totals.total),
            _format_cost(record.estimated_cost.total_cost),
        )
    return table


def _top_models_table(items: list[dict[str, object]]) -> Table:
    table = Table(box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Model", style=ACCENT)
    table.add_column("Provider", style=COOL)
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")
    for item in items:
        estimated = item.get("estimated_cost") or {}
        table.add_row(
            item["model"],
            item["provider"],
            _format_int(item["token_totals"]["total"]),
            _format_cost(estimated.get("total_cost", 0.0)),
        )
    return table


def _recent_sessions_table(records: list[SessionRecord]) -> Table:
    table = Table(box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Session", style=ACCENT)
    table.add_column("Provider", style=COOL)
    table.add_column("Model")
    table.add_column("Attr")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")
    for record in records:
        table.add_row(
            record.anon_session_id,
            record.provider.value,
            record.primary_model or "unknown",
            record.attribution_status or "-",
            _format_int(record.token_totals.total),
            _format_cost(record.estimated_cost.total_cost if record.estimated_cost is not None else 0.0),
        )
    return table


def _format_int(value: int | None) -> str:
    return f"{value or 0:,}"


def _format_cost(value: float | None) -> str:
    return f"${(value or 0.0):,.2f}"


def _format_ratio(value: float) -> str:
    return f"{value * 100:.1f}%"
