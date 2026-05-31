from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
import os
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def local_now() -> datetime:
    return datetime.now().astimezone()


def parse_datetime_value(value: str | None, *, bound: Literal["since", "until"]) -> datetime | None:
    if value is None:
        return None

    raw = value.strip()
    if not raw:
        return None

    relative = _parse_relative(raw)
    if relative is not None:
        return local_now() - relative

    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Invalid {bound} value: {value}") from exc

    if parsed.tzinfo is None:
        if "T" in raw:
            parsed = parsed.astimezone()
        else:
            day_time = time.min if bound == "since" else time.max
            parsed = datetime.combine(parsed.date(), day_time).astimezone()
    return _to_local_datetime(parsed)


def _parse_relative(value: str) -> timedelta | None:
    if len(value) < 2:
        return None
    unit = value[-1].lower()
    amount_text = value[:-1]
    if not amount_text.isdigit():
        return None

    amount = int(amount_text)
    units = {
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
        "w": timedelta(weeks=amount),
    }
    return units.get(unit)


def parse_unix_timestamp(value: int | float | None) -> datetime | None:
    if value is None:
        return None
    return _to_local_datetime(datetime.fromtimestamp(value, tz=timezone.utc))


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return _to_local_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))


def matches_time_window(started_at: datetime | None, updated_at: datetime | None, since: datetime | None, until: datetime | None) -> bool:
    pivot = updated_at or started_at
    if pivot is None:
        return since is None and until is None
    if since is not None and pivot < since:
        return False
    if until is not None and pivot > until:
        return False
    return True


def _to_local_datetime(value: datetime) -> datetime:
    local_timezone = _local_timezone()
    if local_timezone is None:
        return value.astimezone()
    return value.astimezone(local_timezone)


@lru_cache(maxsize=1)
def _local_timezone() -> ZoneInfo | None:
    env_timezone = os.environ.get("TZ")
    if env_timezone:
        timezone_name = env_timezone.strip()
        if timezone_name and not timezone_name.startswith(":"):
            try:
                return ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError:
                pass

    try:
        localtime = Path("/etc/localtime").resolve()
    except OSError:
        return None

    parts = localtime.parts
    try:
        zoneinfo_index = parts.index("zoneinfo")
    except ValueError:
        return None

    timezone_name = "/".join(parts[zoneinfo_index + 1 :])
    if not timezone_name:
        return None
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return None
