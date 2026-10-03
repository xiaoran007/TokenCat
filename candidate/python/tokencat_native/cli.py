from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console

from tokencat_native import __version__
from tokencat_native.engine import Engine, public_dashboard
from tokencat_native.options import Harness, Theme, configuration, make_query, timezone_name
from tokencat_native.render import render_dashboard

app = typer.Typer(
    help="TokenCat native candidate: local dashboard for Codex, Claude Code, OpenCode, and Antigravity.",
    invoke_without_command=True, no_args_is_help=False,
)


def version(value: bool) -> None:
    if value:
        typer.echo(f"TokenCat native candidate {__version__}")
        raise typer.Exit()


@app.callback()
@app.command("dashboard")
def dashboard(
    ctx: typer.Context,
    providers: Optional[List[Harness]] = typer.Option(None, "--provider", case_sensitive=False, help="Filter harnesses."),
    since: str = typer.Option("7d", help="Relative duration (7d, 24h) or ISO date/datetime."),
    until: Optional[str] = typer.Option(None, help="End time; an ISO date includes that whole calendar day."),
    timezone: Optional[str] = typer.Option(None, "--timezone", help="IANA time zone; defaults to the system zone."),
    daily: bool = typer.Option(False, "--daily", help="Use daily buckets."),
    weekly: bool = typer.Option(False, "--weekly", help="Use calendar weeks starting on Monday."),
    monthly: bool = typer.Option(False, "--monthly", help="Use calendar months."),
    json_output: bool = typer.Option(False, "--json", help="Export the candidate dashboard JSON contract."),
    no_price: bool = typer.Option(False, "--no-price", help="Hide terminal cost columns; native queries still calculate prices."),
    theme: Theme = typer.Option(Theme.AUTO, help="Terminal theme: auto, dark, or light."),
    home: Optional[Path] = typer.Option(None, "--home", help="Home directory containing provider data."),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", help="Candidate ledger directory; defaults to ~/.tokencat-candidate."),
    pricing_path: Optional[Path] = typer.Option(None, "--pricing-path", help="Native-compatible price catalog; default is the bundled snapshot."),
    codex_root: Optional[Path] = typer.Option(None, "--codex-root", help="Codex root containing sessions/ and archived_sessions/."),
    claude_roots: Optional[List[Path]] = typer.Option(None, "--claude-root", help="Claude root containing projects/; repeatable."),
    opencode_root: Optional[Path] = typer.Option(None, "--opencode-root", help="OpenCode directory containing opencode.db."),
    antigravity_roots: Optional[List[Path]] = typer.Option(None, "--antigravity-root", help="Antigravity root containing conversations/; repeatable."),
    show_version: bool = typer.Option(False, "--version", callback=version, is_eager=True, help="Show candidate version."),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    if no_price and json_output:
        raise typer.BadParameter("--no-price only changes terminal presentation; --json always exports native cost data.")
    try:
        query = make_query(since=since, until=until, zone=timezone_name(timezone), providers=providers or [],
                           daily=daily, weekly=weekly, monthly=monthly)
        config = configuration(home=home, data_dir=data_dir, pricing_path=pricing_path,
                               codex_root=codex_root, claude_roots=claude_roots or [],
                               opencode_root=opencode_root, antigravity_roots=antigravity_roots or [])
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    try:
        with Engine(config) as engine:
            engine.scan()
            snapshot = engine.query(query)
    except (RuntimeError, ValueError, OSError) as exc:
        typer.echo(f"Candidate error: {exc}", err=True)
        raise typer.Exit(1) from exc
    if json_output:
        typer.echo(json.dumps({"candidate_version": __version__, "query": query,
                               "dashboard": public_dashboard(snapshot)}, ensure_ascii=False))
    else:
        render_dashboard(Console(highlight=False), snapshot, query, theme=theme,
                         show_recent=ctx.parent is not None, show_cost=not no_price)
