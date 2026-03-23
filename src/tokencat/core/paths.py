from __future__ import annotations

from pathlib import Path


def vscode_user_roots(home: Path) -> list[Path]:
    return [
        home / "Library" / "Application Support" / "Code" / "User",
        home / ".config" / "Code" / "User",
    ]


def vscode_workspace_storage_dirs(home: Path) -> list[Path]:
    return [root / "workspaceStorage" for root in vscode_user_roots(home)]


def vscode_copilot_global_storage_dirs(home: Path) -> list[Path]:
    return [root / "globalStorage" / "github.copilot-chat" / "copilotCli" for root in vscode_user_roots(home)]


def opencode_data_dir(home: Path) -> Path:
    return home / ".local" / "share" / "opencode"


def opencode_message_roots(home: Path) -> list[Path]:
    data_dir = opencode_data_dir(home)
    roots = [data_dir / "storage" / "message"]
    roots.extend(sorted(data_dir.glob("project/*/storage/message")))
    return _dedupe_paths(roots)


def opencode_session_roots(home: Path) -> list[Path]:
    data_dir = opencode_data_dir(home)
    roots = [data_dir / "storage" / "session"]
    roots.extend(sorted(data_dir.glob("project/*/storage/session")))
    return _dedupe_paths(roots)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            deduped.append(path)
            seen.add(path)
    return deduped
