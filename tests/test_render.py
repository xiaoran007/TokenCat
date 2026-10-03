from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from rich.panel import Panel
from typer.testing import CliRunner

import tokencat.cli as shared_cli
from tokencat.core.models import DashboardThemeMode, DashboardUsageGranularity
from tokencat.core import render
from tokencat.cli import app
from tokencat.dashboard import load_dashboard
from conftest import PRIVATE_BODY, PRIVATE_ID, claude_row, write_rows


def render_cli(monkeypatch, *, width, theme="dark", flags=()):
    console = Console(file=StringIO(), width=width, height=25, force_terminal=True, color_system="truecolor", record=True)
    monkeypatch.setattr(shared_cli, "console", console)
    result = CliRunner().invoke(app, ["dashboard", "--since", "2026-10-02", "--until", "2026-10-02", "--theme", theme, *flags])
    assert result.exit_code == 0, result.output
    return console.export_text(clear=False), console.export_html(inline_styles=True)


@pytest.mark.parametrize("width", [80, 100, 140])
def test_cli_restores_existing_dashboard_layout_and_palette(source_home, monkeypatch, width):
    text, html = render_cli(monkeypatch, width=width)
    assert "local usage cockpit" in text and "Top Models" in text
    if width >= 100:
        assert any("Overview" in line and "Top Models" in line for line in text.splitlines()), text
    assert "━" in text  # The original SIMPLE_HEAVY tables.
    if width >= 100:
        assert "Cache read" in text and "Cache write" in text
    assert "#d7ba7d" in html and "#1a1a1a" in html
    assert all(len(line) <= width for line in text.splitlines())
    assert PRIVATE_ID not in text and PRIVATE_BODY not in text
    if width < render.COMPACT_DASHBOARD_WIDTH:
        assert "compact tokens: narrow terminal" in text
    else:
        assert "1,050 (1.1K)" in text
    assert text == (Path(__file__).parent / "golden" / f"dashboard-{width}.txt").read_text()


def test_cli_uses_original_light_and_auto_themes(source_home, monkeypatch):
    _, light = render_cli(monkeypatch, width=100, theme="light")
    assert "#8b5e00" in light and "#f7f3ea" in light
    monkeypatch.setenv("COLORFGBG", "0;15")
    _, auto = render_cli(monkeypatch, width=100, theme="auto")
    assert "#8b5e00" in auto and "#f7f3ea" in auto


def test_native_adapter_preserves_cache_writes_reasoning_and_price_ranges(all_sources, monkeypatch):
    row = claude_row()
    row["message"]["usage"]["cache_creation_input_tokens"] = 20_000
    write_rows(all_sources, f".claude/projects/example/{PRIVATE_ID}.jsonl", [row])
    filters = shared_cli.build_filters(None, "2026-10-02", "2026-10-02", None, None, False, False)
    data = load_dashboard(filters, DashboardUsageGranularity.DAILY, pricing_enabled=True)
    usage = data.usage[0]
    assert usage.token_totals.output + usage.token_totals.reasoning == 220
    assert usage.token_totals.cache_write == 20_000
    assert usage.estimated_cost.max_cost > usage.estimated_cost.total_cost
    assert "–" in usage.estimated_cost.display_cost
    table = render._daily_block(usage, palette=render.DARK_PALETTE, compact_tokens=True).renderables[1]
    assert [column.header for column in table.columns] == ["Model", "Input", "Output", "Cache read", "Cache write", "Total", "Est Cost"]
    # Check actual table cells: output includes reasoning exactly once, cache categories remain separate.
    models = usage.models
    output_cells = table.columns[2]._cells
    assert sum(int(str(value)) for value in output_cells) == 220
    assert sum(model.token_totals.cache_write for model in models) == 20_000
    text, _ = render_cli(monkeypatch, width=140)
    assert "–" in text and "Cache write" in text


def test_native_summary_does_not_claim_legacy_attribution_or_source_health(source_home):
    filters = shared_cli.build_filters(None, "2026-10-02", "2026-10-02", None, None, False, False)
    data = load_dashboard(filters, DashboardUsageGranularity.DAILY, pricing_enabled=True)
    assert all(record.attribution_status is None for record in data.sessions)
    assert data.statuses[0].reasons == ["Usage recorded within the query window."]
    overview = render._hero_panel(data.overview, palette=render.DARK_PALETTE, compact_tokens=True)
    assert isinstance(overview, Panel)
    assert "unattributed" not in overview.renderable.renderables[0].renderable.plain
