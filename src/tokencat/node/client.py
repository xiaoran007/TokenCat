from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tokencat.core.models import ScanFilters, ScanResult
from tokencat.node.identity import NodeIdentity
from tokencat.node.protocol import snapshot_request_from_filters
from tokencat.node.snapshot import scan_result_from_snapshot


@dataclass(frozen=True)
class NodeEndpoint:
    node_id: str
    name: str
    base_url: str
    host: str | None = None
    port: int | None = None
    version: str | None = None
    api_version: int = 1
    auth: str = "none"


@dataclass(frozen=True)
class RemoteScan:
    endpoint: NodeEndpoint
    node: NodeIdentity
    result: ScanResult


def fetch_remote_snapshot(
    endpoint: NodeEndpoint,
    filters: ScanFilters,
    *,
    token: str | None,
    timeout: float = 5.0,
    include_paths: bool = False,
    include_titles: bool = False,
) -> RemoteScan:
    payload = snapshot_request_from_filters(filters, include_paths=include_paths, include_titles=include_titles)
    request = Request(
        endpoint.base_url.rstrip("/") + "/v1/snapshot",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(token),
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"{endpoint.name}: HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"{endpoint.name}: {exc.reason}") from exc

    response_payload = json.loads(body)
    if not isinstance(response_payload, dict):
        raise RuntimeError(f"{endpoint.name}: invalid snapshot response")
    node, result = scan_result_from_snapshot(response_payload)
    return RemoteScan(endpoint=endpoint, node=node, result=result)


def fetch_remote_node(base_url: str, *, timeout: float = 5.0) -> NodeEndpoint:
    normalized_url = base_url.rstrip("/")
    request = Request(
        normalized_url + "/v1/node",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"{base_url}: HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"{base_url}: {exc.reason}") from exc

    payload = json.loads(body)
    if not isinstance(payload, dict) or not isinstance(payload.get("node"), dict):
        raise RuntimeError(f"{base_url}: invalid node response")
    node_payload = payload["node"]
    node_id = _required_string(node_payload, "id")
    name = _required_string(node_payload, "name")
    return NodeEndpoint(
        node_id=node_id,
        name=name,
        base_url=normalized_url,
        version=str(node_payload.get("version") or "unknown"),
        api_version=int(node_payload.get("api_version") or 1),
        auth=str(payload.get("auth") or "none"),
    )


def _headers(token: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    raise RuntimeError(f"Missing required node field: {key}")
