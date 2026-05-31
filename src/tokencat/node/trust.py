from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tokencat.node.client import NodeEndpoint

TRUST_STORE_PATH = Path("~/.tokencat/nodes/trust.json").expanduser()
DEFAULT_TOKEN_ENV = "TOKENCAT_NODE_TOKEN"


@dataclass(frozen=True)
class TrustedNode:
    node_id: str
    name: str
    transport: str = "http"
    base_url: str | None = None
    ssh_host: str | None = None
    remote_command: str | None = None
    token_env: str | None = None
    trusted_at: str | None = None

    def to_endpoint(self) -> NodeEndpoint:
        if not self.base_url:
            raise ValueError("HTTP trusted node is missing base_url")
        return NodeEndpoint(
            node_id=self.node_id,
            name=self.name,
            base_url=self.base_url,
            auth="token" if self.token_env else "none",
        )

    def token(self) -> str | None:
        if not self.token_env:
            return None
        return os.environ.get(self.token_env)

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "transport": self.transport,
            "base_url": self.base_url,
            "ssh_host": self.ssh_host,
            "remote_command": self.remote_command,
            "token_env": self.token_env,
            "trusted_at": self.trusted_at,
        }


def load_trusted_nodes(path: Path = TRUST_STORE_PATH) -> list[TrustedNode]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []
    nodes_payload = payload.get("nodes") if isinstance(payload, dict) else None
    if not isinstance(nodes_payload, list):
        return []
    nodes: list[TrustedNode] = []
    for item in nodes_payload:
        if not isinstance(item, dict):
            continue
        node_id = _string_or_none(item.get("node_id"))
        name = _string_or_none(item.get("name"))
        transport = _string_or_none(item.get("transport")) or "http"
        base_url = _string_or_none(item.get("base_url"))
        ssh_host = _string_or_none(item.get("ssh_host"))
        if not node_id or not name:
            continue
        if transport == "http" and not base_url:
            continue
        if transport == "ssh" and not ssh_host:
            continue
        nodes.append(
            TrustedNode(
                node_id=node_id,
                name=name,
                transport=transport,
                base_url=base_url,
                ssh_host=ssh_host,
                remote_command=_string_or_none(item.get("remote_command")),
                token_env=_string_or_none(item.get("token_env")),
                trusted_at=_string_or_none(item.get("trusted_at")),
            )
        )
    return nodes


def save_trusted_nodes(nodes: list[TrustedNode], path: Path = TRUST_STORE_PATH) -> None:
    payload = {
        "nodes": [node.to_dict() for node in sorted(nodes, key=lambda item: (item.name.lower(), item.node_id))]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def merge_trusted_nodes(existing: list[TrustedNode], selected: list[NodeEndpoint], *, token_env: str | None) -> list[TrustedNode]:
    by_id = {node.node_id: node for node in existing}
    now = datetime.now().astimezone().isoformat()
    for endpoint in selected:
        by_id[endpoint.node_id] = TrustedNode(
            node_id=endpoint.node_id,
            name=endpoint.name,
            transport="http",
            base_url=endpoint.base_url,
            token_env=token_env if endpoint.auth == "token" else None,
            trusted_at=by_id.get(endpoint.node_id, TrustedNode(endpoint.node_id, endpoint.name, base_url=endpoint.base_url)).trusted_at or now,
        )
    return list(by_id.values())


def merge_trusted_ssh_nodes(
    existing: list[TrustedNode],
    selected: list[tuple[NodeEndpoint, str]],
    *,
    remote_command: str | None = None,
) -> list[TrustedNode]:
    by_id = {node.node_id: node for node in existing}
    now = datetime.now().astimezone().isoformat()
    for endpoint, ssh_host in selected:
        current = by_id.get(endpoint.node_id)
        by_id[endpoint.node_id] = TrustedNode(
            node_id=endpoint.node_id,
            name=endpoint.name,
            transport="ssh",
            ssh_host=ssh_host,
            remote_command=remote_command,
            trusted_at=(current.trusted_at if current else None) or now,
        )
    return list(by_id.values())


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
