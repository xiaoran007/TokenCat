from __future__ import annotations

from rich import box
from rich.columns import Columns
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from tokencat.core.models import DailyUsageRecord, PricingCatalog, PricingCoverage, ProviderStatus, SessionRecord
from tokencat.core.presentation import (
    filter_displayable_daily_records,
    filter_displayable_model_items,
    filter_displayable_sessions,
    provider_display_name,
)

ACCENT = "#d7ba7d"
MUTED = "#9ba1a6"
COOL = "#89dceb"
SUCCESS = "#a6e3a1"
WARN = "#f9e2af"
ERROR = "#f38ba8"
SURFACE = "on #1a1a1a"


def render_dashboard(
    console: Console,
    *,
    time_label: str,
    statuses: list[ProviderStatus],
    overview: dict[str, object],
    daily: list[DailyUsageRecord],
    sessions: list[SessionRecord],
    pricing_catalog: PricingCatalog | None,
    pricing_coverage: PricingCoverage | None,
    warnings: list[str],
) -> None:
    visible_daily = filter_displayable_daily_records(daily)
    visible_sessions = filter_displayable_sessions(sessions[:6])
    renderables = [
        _brand_panel(time_label, statuses, pricing_catalog, pricing_coverage),
        _hero_panel(overview),
        _daily_panel(visible_daily),
        Panel(_recent_sessions_renderable(visible_sessions), title="Recent Sessions", border_style=ACCENT, box=box.ROUNDED, style=SURFACE),
    ]
    if warnings:
        warning_text = Text("\n".join(f"- {warning}" for warning in warnings), style=WARN)
        renderables.append(Panel(warning_text, title="Warnings", border_style=WARN, box=box.ROUNDED, style=SURFACE))
    console.print(Group(*renderables))


def render_pricing_summary(console: Console, *, catalog: PricingCatalog | None, coverage: PricingCoverage | None, unknown_models: list[str]) -> None:
    table = Table(box=box.SIMPLE_HEAVY, pad_edge=False, collapse_padding=True, padding=(0, 1))
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
    console.print(Panel(table, title="Pricing", border_style=COOL, box=box.ROUNDED, style=SURFACE))


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
        status_line.append(f"{provider_display_name(status.provider)}:{status.status.value}", style=color)

    footer = Text()
    if pricing_catalog is not None:
        footer.append(f"pricing: {pricing_catalog.source}", style=ACCENT)
        if pricing_catalog.refreshed_at:
            footer.append(f"  refreshed {pricing_catalog.refreshed_at}", style=MUTED)
    if pricing_coverage is not None and pricing_coverage.unknown_models:
        footer.append(f"\nunknown pricing: {', '.join(pricing_coverage.unknown_models)}", style=WARN)
    if pricing_coverage is not None and pricing_coverage.unattributed_token_count:
        footer.append(f"\nunattributed tokens: {_format_int(pricing_coverage.unattributed_token_count)}", style=WARN)

    return Panel(Group(header, status_line, footer), border_style=ACCENT, box=box.ROUNDED, style=SURFACE)


def _hero_panel(overview: dict[str, object]) -> Panel:
    totals = overview["token_totals"]
    cost = overview["estimated_cost"]
    secondary = overview.get("secondary_metrics") or {}
    top_models = filter_displayable_model_items(overview.get("top_models") or [])

    primary = Text()
    primary.append(f"{_format_int(totals['total'])}\n", style=f"bold {ACCENT}")
    primary.append("Total tokens\n", style=COOL)
    primary.append(f"{_format_cost(cost['total_cost'])} estimated API cost\n", style=f"bold {WARN}")
    primary.append(
        "  ".join(
            [
                f"{overview['session_count']} sessions",
                f"{overview['model_count']} models",
                f"{secondary.get('provider_count', 0)} providers",
            ]
        )
        + "\n",
        style=MUTED,
    )
    primary.append(
        "  ".join(
            [
                f"coverage {_format_ratio(secondary.get('priced_coverage', 0.0))}",
                f"unknown {_format_int(secondary.get('unknown_model_tokens'))}",
                f"unattributed {_format_int(secondary.get('unattributed_token_count'))}",
            ]
        ),
        style=MUTED,
    )

    ranking = Table(box=None, expand=True, pad_edge=False, collapse_padding=True, padding=(0, 1))
    ranking.add_column("Top models", style=COOL)
    ranking.add_column("Tokens", justify="right")
    ranking.add_column("Cost", justify="right")
    for item in top_models[:5]:
        estimated = item.get("estimated_cost") or {}
        ranking.add_row(
            item["model"],
            _format_int(item["token_totals"]["total"]),
            _format_cost(estimated.get("total_cost", 0.0)),
        )
    if not top_models:
        ranking.add_row("No model data", "-", "-")

    return Panel(
        Columns(
            [
                Panel(primary, title="Overview", border_style=MUTED, box=box.ROUNDED),
                Panel(ranking, title="Top Models", border_style=COOL, box=box.ROUNDED, style=SURFACE),
            ],
            equal=False,
            expand=True,
        ),
        border_style=ACCENT,
        box=box.ROUNDED,
        style=SURFACE,
    )


def _daily_panel(records: list[DailyUsageRecord]) -> Panel:
    if not records:
        return Panel(Text("No usage in this window.", style=MUTED), title="Daily Usage", border_style=MUTED, box=box.ROUNDED, style=SURFACE)

    sections: list[object] = []
    for index, record in enumerate(records):
        if index:
            sections.append(Rule(style=MUTED))
        sections.append(_daily_block(record))
    return Panel(Group(*sections), title="Daily Usage", border_style=MUTED, box=box.ROUNDED, style=SURFACE)


def _daily_block(record: DailyUsageRecord) -> Group:
    header = Text()
    header.append(record.date.isoformat(), style=f"bold {ACCENT}")
    header.append("  ", style=MUTED)
    header.append(f"{_format_int(record.token_totals.total)} total", style=COOL)
    header.append("  ", style=MUTED)
    header.append(f"{_format_cost(record.estimated_cost.total_cost)}", style=WARN)
    header.append("  ", style=MUTED)
    header.append(f"{record.session_count} sessions", style=MUTED)
    header.append("  ", style=MUTED)
    header.append(f"coverage {_format_ratio((record.priced_tokens / record.total_tokens) if record.total_tokens else 0.0)}", style=MUTED)

    table = Table(box=box.SIMPLE_HEAVY, expand=True, pad_edge=False, collapse_padding=True, padding=(0, 1))
    table.add_column("Model", style=ACCENT, width=32, no_wrap=True, overflow="ellipsis")
    table.add_column("Input", justify="right", width=12, no_wrap=True)
    table.add_column("Output", justify="right", width=12, no_wrap=True)
    table.add_column("Cached", justify="right", width=12, no_wrap=True)
    table.add_column("Total", justify="right", width=12, no_wrap=True)
    table.add_column("Est Cost", justify="right", width=8, no_wrap=True)

    visible_models = record.models[:5]
    for model in visible_models:
        table.add_row(
            f"{model.model} ({provider_display_name(model.provider)})",
            _format_int(model.token_totals.input),
            _format_int((model.token_totals.output or 0) + (model.token_totals.reasoning or 0)),
            _format_int(model.token_totals.cached),
            _format_int(model.token_totals.total),
            _format_cost(model.estimated_cost.total_cost),
        )
    if len(record.models) > len(visible_models):
        table.add_row(
            f"+{len(record.models) - len(visible_models)} more models",
            "",
            "",
            "",
            "",
            "",
        )

    return Group(header, table)


def _recent_sessions_renderable(records: list[SessionRecord]) -> Table | Text:
    if not records:
        return Text("No recent sessions in this window.", style=MUTED)
    return _recent_sessions_table(records)


def _recent_sessions_table(records: list[SessionRecord]) -> Table:
    single_provider = len({record.provider.value for record in records}) <= 1 if records else False
    table = Table(box=box.SIMPLE_HEAVY, expand=True, pad_edge=False, collapse_padding=True, padding=(0, 1))
    table.add_column("Session", style=ACCENT)
    if not single_provider:
        table.add_column("Provider", style=COOL)
    table.add_column("Model")
    table.add_column("Attr")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")
    for record in records:
        row = [record.anon_session_id]
        if not single_provider:
            row.append(provider_display_name(record.provider))
        row.extend(
            [
                record.primary_model or "unknown",
                record.attribution_status or "-",
                _format_int(record.token_totals.total),
                _format_cost(record.estimated_cost.total_cost if record.estimated_cost is not None else 0.0),
            ]
        )
        table.add_row(*row)
    return table


def _format_int(value: int | None) -> str:
    number = float(value or 0)
    abs_number = abs(number)
    if abs_number >= 1_000_000_000:
        return f"{int(number):,} ({number / 1_000_000_000:.1f}B)"
    if abs_number >= 1_000_000:
        return f"{int(number):,} ({number / 1_000_000:.1f}M)"
    if abs_number >= 1_000:
        return f"{int(number):,} ({number / 1_000:.1f}K)"
    return f"{int(number):,}"


def _format_cost(value: float | None) -> str:
    return f"${(value or 0.0):,.2f}"


def _format_ratio(value: float) -> str:
    return f"{value * 100:.1f}%"
