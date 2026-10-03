from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tokencat_native import __version__
from tokencat_native.options import Theme

HARNESS_LABELS = {"codex": "Codex", "claude": "Claude Code", "opencode": "OpenCode", "antigravity": "Antigravity"}


def tokens(value: int, *, compact: bool) -> str:
    if compact:
        for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
            if value >= size:
                return f"{value / size:.1f}{suffix}"
    return f"{value:,}"


def money(value: float) -> str:
    if 0 < value < 0.0001:
        return "<$0.0001"
    return f"${value:.4f}" if 0 < value < 0.01 else f"${value:.2f}"


def cost_text(cost: dict) -> str:
    if cost["unpriced_events"] and cost["priced_tokens"] == 0:
        return "No price record"
    minimum, maximum = cost["min_usd"], cost["max_usd"]
    value = money(minimum) if minimum == maximum else f"{money(minimum)}–{money(maximum)}"
    return f"Known {value}" if cost["unpriced_events"] else value


def coverage(cost: dict) -> str:
    return f"{cost['priced_tokens'] / cost['total_tokens']:.0%}" if cost["total_tokens"] else "—"


def _accent(theme: Theme) -> str:
    if theme is Theme.AUTO:
        background = os.environ.get("COLORFGBG", "").rsplit(";", 1)[-1]
        theme = Theme.LIGHT if background.isdigit() and int(background) >= 7 else Theme.DARK
    return "blue" if theme is Theme.LIGHT else "cyan"


def _date(milliseconds: int, zone: ZoneInfo) -> datetime:
    return datetime.fromtimestamp(milliseconds / 1000, tz=zone)


def render_dashboard(console: Console, snapshot: dict, query: dict, *, theme: Theme,
                     show_recent: bool, show_cost: bool) -> None:
    compact = console.width < 110
    accent = _accent(theme)
    zone = ZoneInfo(query["timezone"])
    summary = snapshot["summary"]
    active = ", ".join(HARNESS_LABELS[row["id"]] for row in snapshot["providers"]) or "None in this window"
    window = f"{_date(query['since_ms'], zone):%Y-%m-%d %H:%M} → {_date(query['until_ms'], zone):%Y-%m-%d %H:%M} ({zone.key})"
    brand = Text(f"TokenCat · native candidate {__version__}\n", style=f"bold {accent}")
    brand.append(window + "\n", style="dim")
    brand.append(f"Active harnesses: {active}")
    if show_cost:
        brand.append(f"\nPrices: {snapshot['catalog_id']} · retrieved {snapshot['catalog_retrieved_at']}", style="dim")
    panels = [Panel(brand, border_style=accent)]

    hero = Table.grid(padding=(0, 3))
    hero.add_row("Total tokens", tokens(summary["cost"]["total_tokens"], compact=compact))
    if show_cost:
        hero.add_row("Estimated cost", cost_text(summary["cost"]))
        hero.add_row("Pricing coverage", coverage(summary["cost"]))
        hero.add_row("Unpriced / uncertain events", f"{summary['cost']['unpriced_events']} / {summary['cost']['uncertain_events']}")
    hero.add_row("Sessions / identified models / harnesses", " / ".join(map(str, (
        sum(row["summary"]["event_count"] > 0 for row in snapshot["sessions"]),
        sum(row["id"] != "unknown" for row in snapshot["models"]), len(snapshot["providers"]),
    ))))
    hero.add_row("Incomplete events", str(summary["incomplete_events"]))
    top = Table(box=None, padding=(0, 1), expand=True)
    top.add_column("Top models")
    top.add_column("Tokens", justify="right")
    if show_cost:
        top.add_column("Est cost", justify="right")
    for row in sorted(snapshot["models"], key=lambda row: (-row["summary"]["cost"]["total_tokens"], row["id"]))[:5]:
        cells = [row["label"], tokens(row["summary"]["cost"]["total_tokens"], compact=compact)]
        if show_cost:
            cells.append(cost_text(row["summary"]["cost"]))
        top.add_row(*cells)
    panels.append(Panel(Group(hero, top), title="Overview", border_style=accent))

    blocks = []
    for bucket in snapshot["timeline"]:
        if not bucket["summary"]["event_count"]:
            continue
        date = _date(bucket["timestamp_ms"], zone)
        label = date.strftime("%Y-%m") if query["granularity"] == "month" else date.strftime("%Y-%m-%d")
        if query["granularity"] == "week":
            label = "Week of " + label
        details = bucket["details"]
        heading = f"{label}  ·  {tokens(bucket['summary']['cost']['total_tokens'], compact=compact)} tokens  ·  {details['session_count']} sessions"
        if show_cost:
            heading += f"  ·  {cost_text(bucket['summary']['cost'])}  ·  coverage {coverage(bucket['summary']['cost'])}"
        table = Table(box=None, expand=True, padding=(0, 1))
        table.add_column("Model (harness)", style=accent)
        for column in ("Input", "Cache read", "Cache write", "Output", "Total"):
            table.add_column(column, justify="right", no_wrap=True)
        if show_cost:
            table.add_column("Est cost", justify="right")
        for row in details["models"]:
            usage = row["summary"]
            cells = [f"{row['label']} ({HARNESS_LABELS[row['provider']]})"]
            cells += [tokens(usage[field], compact=compact) for field in (
                "input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens",
            )]
            cells.append(tokens(usage["cost"]["total_tokens"], compact=compact))
            if show_cost:
                cells.append(cost_text(usage["cost"]))
            table.add_row(*cells)
        blocks += [Text(heading, style="bold"), table]
    panels.append(Panel(Group(*blocks) if blocks else Text("No usage in this window.", style="dim"),
                        title={"day": "Daily usage", "week": "Weekly usage", "month": "Monthly usage"}[query["granularity"]],
                        border_style=accent))

    if show_recent:
        recent = Table(box=None, expand=True, padding=(0, 1))
        for column in ("Session", "Harness", "Model", "State", "Tokens"):
            recent.add_column(column, justify="right" if column == "Tokens" else "left")
        if show_cost:
            recent.add_column("Est cost", justify="right")
        for row in [row for row in snapshot["sessions"] if row["summary"]["event_count"] > 0][:6]:
            usage = row["summary"]
            cells = [row["label"], HARNESS_LABELS[row["provider"]], row.get("primary_model", "unknown"),
                     "Incomplete" if usage["incomplete_events"] else "Recorded",
                     tokens(usage["cost"]["total_tokens"], compact=compact)]
            if show_cost:
                cells.append(cost_text(usage["cost"]))
            recent.add_row(*cells)
        panels.append(Panel(recent, title="Recent sessions", border_style=accent))
    report = snapshot["last_scan"]
    if report is not None:
        warnings = list(report["warnings"])
        if report["undated_events"]:
            warnings.append(f"{report['undated_events']} undated events ({report['undated_tokens']:,} tokens) are outside time-window totals.")
        if warnings:
            panels.append(Panel(Text("\n".join(f"• {warning}" for warning in warnings)), title="Warnings", border_style="yellow"))
    console.print(Group(*panels))
