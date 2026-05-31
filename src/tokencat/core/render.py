from __future__ import annotations

from dataclasses import dataclass
from os import environ

from rich import box
from rich.columns import Columns
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from tokencat.core.models import (
    DashboardThemeMode,
    DashboardUsageGranularity,
    DailyUsageRecord,
    PricingCatalog,
    PricingCoverage,
    ProviderName,
    ProviderStatus,
    SessionRecord,
)
from tokencat.core.presentation import (
    filter_displayable_daily_records,
    filter_displayable_model_items,
    filter_displayable_sessions,
    provider_display_name,
)
from tokencat.core.updates import UpdateNotice


@dataclass(frozen=True)
class DashboardPalette:
    accent: str
    muted: str
    cool: str
    success: str
    warn: str
    error: str
    surface: str


DARK_PALETTE = DashboardPalette(
    accent="#d7ba7d",
    muted="#9ba1a6",
    cool="#89dceb",
    success="#a6e3a1",
    warn="#f9e2af",
    error="#f38ba8",
    surface="on #1a1a1a",
)

LIGHT_PALETTE = DashboardPalette(
    accent="#8b5e00",
    muted="#5f6368",
    cool="#006d77",
    success="#1b7f3b",
    warn="#a15c00",
    error="#b42318",
    surface="on #f7f3ea",
)

COMPACT_DASHBOARD_WIDTH = 121


def render_dashboard(
    console: Console,
    *,
    time_label: str,
    statuses: list[ProviderStatus],
    overview: dict[str, object],
    daily: list[DailyUsageRecord],
    sessions: list[SessionRecord],
    nodes: list[dict[str, object]] | None = None,
    pricing_catalog: PricingCatalog | None,
    pricing_coverage: PricingCoverage | None,
    warnings: list[str],
    show_recent_sessions: bool = True,
    usage_granularity: DashboardUsageGranularity = DashboardUsageGranularity.DAILY,
    theme: DashboardThemeMode = DashboardThemeMode.DARK,
    update_notice: UpdateNotice | None = None,
) -> None:
    palette = _palette_for_theme(theme)
    compact_tokens = console.width < COMPACT_DASHBOARD_WIDTH
    visible_daily = _filter_dashboard_daily_records(daily)
    visible_sessions = filter_displayable_sessions(sessions[:6])
    renderables = [
        _brand_panel(
            time_label,
            statuses,
            pricing_catalog,
            pricing_coverage,
            palette=palette,
            update_notice=update_notice,
            compact_tokens=compact_tokens,
        ),
        _hero_panel(overview, palette=palette, compact_tokens=compact_tokens),
    ]
    if nodes:
        renderables.append(_nodes_panel(nodes, overview=overview, palette=palette, compact_tokens=compact_tokens))
    renderables.append(_daily_panel(visible_daily, granularity=usage_granularity, palette=palette, compact_tokens=compact_tokens))
    if show_recent_sessions:
        renderables.append(
            Panel(
                _recent_sessions_renderable(visible_sessions, palette=palette, compact_tokens=compact_tokens),
                title="Recent Sessions",
                border_style=palette.accent,
                box=box.ROUNDED,
                style=palette.surface,
            )
        )
    if warnings:
        warning_text = Text("\n".join(f"- {warning}" for warning in warnings), style=palette.warn)
        renderables.append(Panel(warning_text, title="Warnings", border_style=palette.warn, box=box.ROUNDED, style=palette.surface))
    console.print(Group(*renderables))


def render_pricing_summary(console: Console, *, catalog: PricingCatalog | None, coverage: PricingCoverage | None, unknown_models: list[str]) -> None:
    palette = DARK_PALETTE
    table = Table(box=box.SIMPLE_HEAVY, pad_edge=False, collapse_padding=True, padding=(0, 1))
    table.add_column("Metric", style=palette.accent)
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
    console.print(Panel(table, title="Pricing", border_style=palette.cool, box=box.ROUNDED, style=palette.surface))


def resolve_dashboard_theme(mode: DashboardThemeMode, env: dict[str, str] | None = None) -> DashboardThemeMode:
    if mode is not DashboardThemeMode.AUTO:
        return mode

    colorfgbg = (env or environ).get("COLORFGBG")
    if not colorfgbg:
        return DashboardThemeMode.DARK

    background = colorfgbg.rsplit(";", 1)[-1].strip()
    if not background.isdigit():
        return DashboardThemeMode.DARK

    return DashboardThemeMode.LIGHT if int(background) >= 7 else DashboardThemeMode.DARK


def _brand_panel(
    time_label: str,
    statuses: list[ProviderStatus],
    pricing_catalog: PricingCatalog | None,
    pricing_coverage: PricingCoverage | None,
    *,
    palette: DashboardPalette,
    update_notice: UpdateNotice | None,
    compact_tokens: bool,
) -> Panel:
    header = Text()
    header.append("tokencat", style=f"bold {palette.accent}")
    header.append("  local usage cockpit", style=palette.muted)
    header.append(f"\nwindow: {time_label}", style=palette.cool)
    if compact_tokens:
        header.append("\ncompact tokens: narrow terminal", style=palette.muted)

    status_line = Text()
    display_statuses = _dedupe_provider_statuses(statuses)
    for index, status in enumerate(display_statuses):
        if index:
            status_line.append("  ")
        color = _provider_status_color(status, palette)
        status_line.append("● ", style=color)
        status_line.append(provider_display_name(status.provider), style=color)

    update_line = Text()
    if update_notice is not None:
        update_line.append(
            f"update available: {update_notice.latest_version} (local {update_notice.current_version})",
            style=palette.warn,
        )

    footer = Text()
    if pricing_catalog is not None:
        footer.append(f"pricing: {pricing_catalog.source}", style=palette.accent)
        if pricing_catalog.refreshed_at:
            footer.append(f"  refreshed {pricing_catalog.refreshed_at}", style=palette.muted)
    if pricing_coverage is not None and pricing_coverage.unknown_models:
        footer.append(f"\nunknown pricing: {', '.join(pricing_coverage.unknown_models)}", style=palette.warn)
    if pricing_coverage is not None and pricing_coverage.unattributed_token_count:
        footer.append(
            f"\nunattributed tokens: {_format_token_count(pricing_coverage.unattributed_token_count, compact=compact_tokens)}",
            style=palette.warn,
        )

    lines: list[object] = [header, status_line]
    if update_notice is not None:
        lines.append(update_line)
    if footer.plain:
        lines.append(footer)
    return Panel(Group(*lines), border_style=palette.accent, box=box.ROUNDED, style=palette.surface)


def _hero_panel(overview: dict[str, object], *, palette: DashboardPalette, compact_tokens: bool) -> Panel:
    totals = overview["token_totals"]
    cost = overview["estimated_cost"]
    secondary = overview.get("secondary_metrics") or {}
    top_models = [
        item for item in filter_displayable_model_items(overview.get("top_models") or []) if _model_item_total(item) > 0
    ]

    primary = Text()
    primary.append(f"{_format_token_count(totals['total'], compact=compact_tokens)}\n", style=f"bold {palette.accent}")
    primary.append("Total tokens\n", style=palette.cool)
    overview_pricing_status = "fallback_priced" if secondary.get("fallback_priced_tokens", 0) else "priced"
    primary.append(
        f"{_format_cost(cost['total_cost'])} estimated API cost\n",
        style=f"bold {_cost_style(cost.get('total_cost'), overview_pricing_status, palette)}",
    )
    primary.append(
        "  ".join(
            [
                f"{overview['session_count']} sessions",
                f"{overview['model_count']} models",
                f"{secondary.get('provider_count', 0)} providers",
            ]
        )
        + "\n",
        style=palette.muted,
    )
    primary.append(
        "  ".join(
            [
                f"coverage {_format_ratio(secondary.get('priced_coverage', 0.0))}",
                f"unknown {_format_token_count(secondary.get('unknown_model_tokens'), compact=compact_tokens)}",
                f"unattributed {_format_token_count(secondary.get('unattributed_token_count'), compact=compact_tokens)}",
            ]
        ),
        style=palette.muted,
    )

    ranking = Table(box=None, expand=True, pad_edge=False, collapse_padding=True, padding=(0, 1))
    ranking.add_column("Top models", style=palette.cool)
    ranking.add_column("Tokens", justify="right")
    ranking.add_column("Cost", justify="right")
    for item in top_models[:5]:
        estimated = item.get("estimated_cost") or {}
        ranking.add_row(
            item["model"],
            _format_token_count(item["token_totals"]["total"], compact=compact_tokens),
            _cost_text(estimated.get("total_cost", 0.0), item.get("pricing_status"), palette),
        )
    if not top_models:
        ranking.add_row("No model data", "-", "-")

    return Panel(
        Columns(
            [
                Panel(primary, title="Overview", border_style=palette.muted, box=box.ROUNDED),
                Panel(ranking, title="Top Models", border_style=palette.cool, box=box.ROUNDED, style=palette.surface),
            ],
            equal=False,
            expand=True,
        ),
        border_style=palette.accent,
        box=box.ROUNDED,
        style=palette.surface,
    )


def _daily_panel(
    records: list[DailyUsageRecord],
    *,
    granularity: DashboardUsageGranularity,
    palette: DashboardPalette,
    compact_tokens: bool,
) -> Panel:
    title = {
        DashboardUsageGranularity.DAILY: "Daily Usage",
        DashboardUsageGranularity.WEEKLY: "Weekly Usage",
        DashboardUsageGranularity.MONTHLY: "Monthly Usage",
    }[granularity]
    if not records:
        return Panel(Text("No usage in this window.", style=palette.muted), title=title, border_style=palette.muted, box=box.ROUNDED, style=palette.surface)

    sections: list[object] = []
    for index, record in enumerate(records):
        if index:
            sections.append(Rule(style=palette.muted))
        sections.append(_daily_block(record, palette=palette, compact_tokens=compact_tokens))
    return Panel(Group(*sections), title=title, border_style=palette.muted, box=box.ROUNDED, style=palette.surface)


def _nodes_panel(
    nodes: list[dict[str, object]],
    *,
    overview: dict[str, object],
    palette: DashboardPalette,
    compact_tokens: bool,
) -> Panel:
    total_tokens = _dict_token_total(overview.get("token_totals"))
    visible_nodes = [node for node in nodes if _dict_token_total(node.get("token_totals")) > 0 or node.get("session_count")]
    if not visible_nodes:
        return Panel(Text("No node usage in this window.", style=palette.muted), title="Nodes", border_style=palette.muted, box=box.ROUNDED, style=palette.surface)

    table = Table(box=box.SIMPLE_HEAVY, expand=True, pad_edge=False, collapse_padding=True, padding=(0, 1))
    node_width = 18 if compact_tokens else 24
    table.add_column("Node", style=palette.accent, width=node_width, no_wrap=True, overflow="ellipsis")
    table.add_column("Sessions", justify="right", width=8, no_wrap=True)
    table.add_column("Providers", justify="right", width=9, no_wrap=True)
    table.add_column("Models", justify="right", width=7, no_wrap=True)
    table.add_column("Tokens", justify="right", width=8 if compact_tokens else 12, no_wrap=True)
    table.add_column("Share", justify="right", width=7, no_wrap=True)
    table.add_column("Cost", justify="right", width=8, no_wrap=True)

    for node in visible_nodes[:8]:
        node_tokens = _dict_token_total(node.get("token_totals"))
        cost = node.get("estimated_cost") if isinstance(node.get("estimated_cost"), dict) else {}
        table.add_row(
            str(node.get("node_name") or "unknown"),
            str(node.get("session_count") or 0),
            str(node.get("provider_count") or 0),
            str(node.get("model_count") or 0),
            _format_token_count(node_tokens, compact=compact_tokens),
            _format_ratio((node_tokens / total_tokens) if total_tokens else 0.0),
            _format_cost(cost.get("total_cost") if isinstance(cost, dict) else 0.0),
        )
    if len(visible_nodes) > 8:
        table.add_row(f"+{len(visible_nodes) - 8} more nodes", "", "", "", "", "", "")

    return Panel(table, title="Nodes", border_style=palette.cool, box=box.ROUNDED, style=palette.surface)


def _daily_block(record: DailyUsageRecord, *, palette: DashboardPalette, compact_tokens: bool) -> Group:
    header = Text()
    header.append(record.label or record.date.isoformat(), style=f"bold {palette.accent}")
    header.append("  ", style=palette.muted)
    header.append(f"{_format_token_count(record.token_totals.total, compact=compact_tokens)} total", style=palette.cool)
    header.append("  ", style=palette.muted)
    header.append(
        f"{_format_cost(record.estimated_cost.total_cost)}",
        style=_cost_style(record.estimated_cost.total_cost, _daily_pricing_status(record), palette),
    )
    header.append("  ", style=palette.muted)
    header.append(f"{record.session_count} sessions", style=palette.muted)
    header.append("  ", style=palette.muted)
    header.append(f"coverage {_format_ratio((record.priced_tokens / record.total_tokens) if record.total_tokens else 0.0)}", style=palette.muted)

    table = Table(box=box.SIMPLE_HEAVY, expand=True, pad_edge=False, collapse_padding=True, padding=(0, 1))
    model_width = 18 if compact_tokens else 26
    token_width = 10 if compact_tokens else 16
    table.add_column("Model", style=palette.accent, width=model_width, no_wrap=True, overflow="ellipsis")
    table.add_column("Input", justify="right", width=token_width, no_wrap=True)
    table.add_column("Output", justify="right", width=token_width, no_wrap=True)
    table.add_column("Cached", justify="right", width=token_width, no_wrap=True)
    table.add_column("Total", justify="right", width=token_width, no_wrap=True)
    table.add_column("Est Cost", justify="right", width=8, no_wrap=True)

    visible_models = record.models[:5]
    for model in visible_models:
        table.add_row(
            _daily_model_label(model),
            _format_token_count(model.token_totals.input, compact=compact_tokens),
            _format_token_count((model.token_totals.output or 0) + (model.token_totals.reasoning or 0), compact=compact_tokens),
            _format_token_count(model.token_totals.cached, compact=compact_tokens),
            _format_token_count(model.token_totals.total, compact=compact_tokens),
            _cost_text(model.estimated_cost.total_cost, model.pricing_status, palette),
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


def _daily_model_label(model) -> str:
    label = f"{model.model} ({provider_display_name(model.provider)})"
    nodes = sorted(getattr(model, "node_names", set()) or [])
    if not nodes:
        return label
    if len(nodes) == 1:
        return f"{label} @ {nodes[0]}"
    return f"{label} @ {nodes[0]} +{len(nodes) - 1}"


def _filter_dashboard_daily_records(records: list[DailyUsageRecord]) -> list[DailyUsageRecord]:
    visible: list[DailyUsageRecord] = []
    for record in filter_displayable_daily_records(records):
        models = [model for model in record.models if _token_total(model.token_totals) > 0]
        if not models and _token_total(record.token_totals) == 0:
            continue
        visible.append(record if len(models) == len(record.models) else DailyUsageRecord(
            date=record.date,
            label=record.label,
            providers=set(record.providers),
            token_totals=record.token_totals,
            session_count=record.session_count,
            estimated_cost=record.estimated_cost,
            priced_tokens=record.priced_tokens,
            total_tokens=record.total_tokens,
            models=models,
        ))
    return visible


def _model_item_total(item: dict[str, object]) -> int:
    token_totals = item.get("token_totals")
    if not isinstance(token_totals, dict):
        return 0
    total = token_totals.get("total")
    if isinstance(total, int):
        return total
    return sum(value for value in token_totals.values() if isinstance(value, int))


def _dict_token_total(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    total = value.get("total")
    if isinstance(total, int):
        return total
    return sum(item for item in value.values() if isinstance(item, int))


def _token_total(tokens) -> int:
    total = tokens.total if hasattr(tokens, "total") else None
    if isinstance(total, int):
        return total
    values = tokens.to_dict().values() if hasattr(tokens, "to_dict") else []
    return sum(value for value in values if isinstance(value, int))


def _recent_sessions_renderable(records: list[SessionRecord], *, palette: DashboardPalette, compact_tokens: bool) -> Table | Text:
    if not records:
        return Text("No recent sessions in this window.", style=palette.muted)
    return _recent_sessions_table(records, palette=palette, compact_tokens=compact_tokens)


def _recent_sessions_table(records: list[SessionRecord], *, palette: DashboardPalette, compact_tokens: bool) -> Table:
    single_provider = len({record.provider.value for record in records}) <= 1 if records else False
    table = Table(box=box.SIMPLE_HEAVY, expand=True, pad_edge=False, collapse_padding=True, padding=(0, 1))
    table.add_column("Session", style=palette.accent)
    if not single_provider:
        table.add_column("Provider", style=palette.cool)
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
                _format_token_count(record.token_totals.total, compact=compact_tokens),
                _cost_text(
                    record.estimated_cost.total_cost if record.estimated_cost is not None else 0.0,
                    record.pricing_status,
                    palette,
                ),
            ]
        )
        table.add_row(*row)
    return table


def _provider_status_color(status: ProviderStatus, palette: DashboardPalette) -> str:
    if status.status.value == "supported":
        return palette.success
    if status.status.value == "partial":
        return palette.warn
    return palette.error


def _dedupe_provider_statuses(statuses: list[ProviderStatus]) -> list[ProviderStatus]:
    best_by_provider: dict[object, ProviderStatus] = {}
    for status in statuses:
        current = best_by_provider.get(status.provider)
        if current is None or _provider_status_rank(status) > _provider_status_rank(current):
            best_by_provider[status.provider] = status
    provider_order = {
        ProviderName.CODEX: 0,
        ProviderName.CLAUDE: 1,
        ProviderName.GEMINI: 2,
        ProviderName.COPILOT: 3,
    }
    return [
        best_by_provider[provider]
        for provider in sorted(best_by_provider, key=lambda value: (provider_order.get(value, 99), value.value))
    ]


def _provider_status_rank(status: ProviderStatus) -> int:
    order = {
        "not_found": 0,
        "unsupported": 0,
        "partial": 1,
        "supported": 2,
    }
    return order.get(status.status.value, 0)


def _palette_for_theme(theme: DashboardThemeMode) -> DashboardPalette:
    return LIGHT_PALETTE if theme is DashboardThemeMode.LIGHT else DARK_PALETTE


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


def _format_token_count(value: int | None, *, compact: bool) -> str:
    return _format_compact_int(value) if compact else _format_int(value)


def _format_compact_int(value: int | None) -> str:
    number = float(value or 0)
    abs_number = abs(number)
    if abs_number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}".rstrip("0").rstrip(".") + "B"
    if abs_number >= 1_000_000:
        return f"{number / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if abs_number >= 1_000:
        return f"{number / 1_000:.0f}K"
    return f"{int(number):,}"


def _format_cost(value: float | None) -> str:
    return f"${(value or 0.0):,.2f}"


def _format_ratio(value: float) -> str:
    return f"{value * 100:.1f}%"


def _cost_text(value: float | None, pricing_status: object, palette: DashboardPalette) -> Text:
    return Text(_format_cost(value), style=_cost_style(value, pricing_status, palette))


def _cost_style(value: float | None, pricing_status: object, palette: DashboardPalette) -> str:
    if not value:
        return palette.muted
    if pricing_status == "fallback_priced":
        return palette.warn
    if pricing_status == "priced":
        return palette.success
    return palette.muted


def _daily_pricing_status(record: DailyUsageRecord) -> str | None:
    status: str | None = None
    for model in record.models:
        status = _pick_dashboard_pricing_status(status, model.pricing_status)
    return status


def _pick_dashboard_pricing_status(current: str | None, incoming: str | None) -> str | None:
    order = {
        None: 0,
        "priced": 1,
        "fallback_priced": 2,
        "partial": 3,
        "unknown_model": 4,
        "unattributed": 5,
        "unpriced": 6,
    }
    if current is None:
        return incoming
    if incoming is None:
        return current
    return incoming if order.get(incoming, 0) > order.get(current, 0) else current
