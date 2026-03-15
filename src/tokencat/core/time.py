from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Literal


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
    return parsed.astimezone()


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
    return datetime.fromtimestamp(value, tz=UTC).astimezone()


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()


def matches_time_window(started_at: datetime | None, updated_at: datetime | None, since: datetime | None, until: datetime | None) -> bool:
    pivot = updated_at or started_at
    if pivot is None:
        return since is None and until is None
    if since is not None and pivot < since:
        return False
    if until is not None and pivot > until:
        return False
    return True
