from __future__ import annotations

import json
import os
import socket
import uuid
from dataclasses import dataclass
from pathlib import Path

from tokencat import __version__


NODE_CONFIG_DIR = Path("~/.tokencat").expanduser()
NODE_IDENTITY_PATH = NODE_CONFIG_DIR / "node.json"


@dataclass(frozen=True)
class NodeIdentity:
    node_id: str
    name: str
    version: str
    api_version: int = 1

    @property
    def short_id(self) -> str:
        return self.node_id.replace("-", "")[:8]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.node_id,
            "name": self.name,
            "version": self.version,
            "api_version": self.api_version,
        }


def load_or_create_identity(path: Path = NODE_IDENTITY_PATH) -> NodeIdentity:
    payload = _read_identity_payload(path)
    if payload is None:
        payload = {
            "id": str(uuid.uuid4()),
            "name": _default_node_name(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    node_id = _as_non_empty_string(payload.get("id")) or str(uuid.uuid4())
    name = _as_non_empty_string(payload.get("name")) or _default_node_name()
    return NodeIdentity(node_id=node_id, name=name, version=__version__)


def apply_node_identity(records, identity: NodeIdentity) -> None:
    for record in records:
        record.node_id = identity.node_id
        record.node_name = identity.name
        if not record.anon_session_id.startswith(f"{identity.short_id}:"):
            record.anon_session_id = f"{identity.short_id}:{record.anon_session_id}"


def _read_identity_payload(path: Path) -> dict[str, object] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _default_node_name() -> str:
    return os.environ.get("TOKENCAT_NODE_NAME") or socket.gethostname().split(".")[0] or "tokencat-node"


def _as_non_empty_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
