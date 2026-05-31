from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SSHHostCandidate:
    alias: str
    hostname: str | None = None
    user: str | None = None
    port: str | None = None
    identity_file: str | None = None

    @property
    def address(self) -> str:
        host = self.hostname or self.alias
        prefix = f"{self.user}@" if self.user else ""
        suffix = f":{self.port}" if self.port else ""
        return f"{prefix}{host}{suffix}"


def load_ssh_host_candidates(path: Path | None = None) -> list[SSHHostCandidate]:
    config_path = path or Path.home() / ".ssh" / "config"
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []

    candidates: list[SSHHostCandidate] = []
    current_aliases: list[str] = []
    current: dict[str, str] = {}

    def flush() -> None:
        if not current_aliases:
            return
        for alias in current_aliases:
            if _is_wildcard_alias(alias):
                continue
            candidates.append(
                SSHHostCandidate(
                    alias=alias,
                    hostname=current.get("hostname"),
                    user=current.get("user"),
                    port=current.get("port"),
                    identity_file=current.get("identityfile"),
                )
            )

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        key = parts[0].lower()
        value = parts[1].strip()
        if key == "host":
            flush()
            current_aliases = value.split()
            current = {}
            continue
        if not current_aliases:
            continue
        if key in {"hostname", "user", "port", "identityfile"}:
            current[key] = value

    flush()
    return candidates


def _is_wildcard_alias(alias: str) -> bool:
    return any(marker in alias for marker in ("*", "?", "!"))
