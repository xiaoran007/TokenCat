from __future__ import annotations

import os
import re
from datetime import date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class Harness(str, Enum):
    CODEX = "codex"
    CLAUDE = "claude"
    OPENCODE = "opencode"
    ANTIGRAVITY = "antigravity"


class Theme(str, Enum):
    AUTO = "auto"
    DARK = "dark"
    LIGHT = "light"


def timezone_name(value: str | None) -> str:
    name = value or os.environ.get("TZ")
    if not name:
        parts = Path("/etc/localtime").resolve().parts
        if "zoneinfo" not in parts:
            raise ValueError("Cannot identify the system time zone; pass --timezone with an IANA name.")
        name = "/".join(parts[parts.index("zoneinfo") + 1:])
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown time zone: {name}") from exc
    return name


def parse_bound(value: str, *, until: bool, now: datetime) -> datetime:
    match = re.fullmatch(r"(\d+)([mhdw])", value)
    if match:
        amount = int(match[1])
        return now - timedelta(**{dict(m="minutes", h="hours", d="days", w="weeks")[match[2]]: amount})
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            day = date.fromisoformat(value)
            if until:
                day += timedelta(days=1)
            return datetime.combine(day, time.min, tzinfo=now.tzinfo)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=now.tzinfo) if parsed.tzinfo is None else parsed
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid time bound: {value}") from exc


def make_query(*, since: str, until: str | None, zone: str, providers: list[Harness],
               daily: bool, weekly: bool, monthly: bool, now: datetime | None = None) -> dict:
    if sum((daily, weekly, monthly)) > 1:
        raise ValueError("Choose at most one of --daily, --weekly, or --monthly.")
    current = now or datetime.now(ZoneInfo(zone))
    try:
        start = parse_bound(since, until=False, now=current)
        end = parse_bound(until, until=True, now=current) if until else current
    except OverflowError as exc:
        raise ValueError("Time bound is outside the supported calendar range.") from exc
    since_ms, until_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    if since_ms >= until_ms:
        raise ValueError("Query end must be after start.")
    days = (until_ms - since_ms) / 86_400_000
    granularity = "month" if monthly else "week" if weekly else "day" if daily else (
        "month" if days > 42 else "week" if days > 14 else "day"
    )
    return {"since_ms": since_ms, "until_ms": until_ms, "timezone": zone,
            "providers": [provider.value for provider in providers] or None,
            "granularity": granularity, "show_paths": False, "include_details": True}


def configuration(*, home: Path | None, data_dir: Path | None, pricing_path: Path | None,
                  codex_root: Path | None, claude_roots: list[Path], opencode_root: Path | None,
                  antigravity_roots: list[Path]) -> dict:
    source_home = (home or Path.home()).expanduser().resolve()
    if home is None and not claude_roots:
        if os.environ.get("CLAUDE_CONFIG_DIR"):
            claude_roots = [Path(value) for value in os.environ["CLAUDE_CONFIG_DIR"].split(os.pathsep) if value]
        elif os.environ.get("XDG_CONFIG_HOME"):
            claude_roots = [Path(os.environ["XDG_CONFIG_HOME"]) / "claude", source_home / ".claude"]
    directory = (data_dir or source_home / ".tokencat-candidate").expanduser().resolve()
    def path(value: Path | None):
        return str(value.expanduser().resolve()) if value is not None else None
    return {"home": str(source_home), "database_path": str(directory / "usage.sqlite3"),
            "pricing_path": path(pricing_path), "codex_root": path(codex_root),
            "claude_roots": [path(root) for root in claude_roots], "opencode_root": path(opencode_root),
            "antigravity_roots": [path(root) for root in antigravity_roots]}
