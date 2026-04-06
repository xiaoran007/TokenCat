from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import urlopen

PYPI_VERSION_URL = "https://pypi.org/pypi/tokencat/json"


@dataclass(slots=True)
class UpdateNotice:
    current_version: str
    latest_version: str


def check_latest_version(current_version: str, *, timeout: float = 2.0) -> UpdateNotice | None:
    latest_version = _fetch_latest_version(timeout=timeout)
    if latest_version is None:
        return None

    current_parts = _parse_simple_version(current_version)
    latest_parts = _parse_simple_version(latest_version)
    if current_parts is None or latest_parts is None:
        return None
    if latest_parts <= current_parts:
        return None
    return UpdateNotice(current_version=current_version, latest_version=latest_version)


def _fetch_latest_version(*, timeout: float) -> str | None:
    try:
        with urlopen(PYPI_VERSION_URL, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, URLError, json.JSONDecodeError):
        return None

    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    version = info.get("version")
    return version.strip() if isinstance(version, str) and version.strip() else None


def _parse_simple_version(value: str) -> tuple[int, ...] | None:
    parts = value.split(".")
    if not parts:
        return None
    parsed: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        parsed.append(int(part))
    return tuple(parsed)
