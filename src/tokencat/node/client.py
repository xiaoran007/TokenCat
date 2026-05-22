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


def _headers(token: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
