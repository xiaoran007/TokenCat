from __future__ import annotations

from dataclasses import dataclass

from tokencat.core.models import ScanFilters, ScanResult
from tokencat.node.client import NodeEndpoint, fetch_remote_snapshot
from tokencat.node.discovery import DiscoveryUnavailable, discover_nodes
from tokencat.node.identity import NodeIdentity, apply_node_identity
from tokencat.node.trust import TrustedNode, load_trusted_nodes
from tokencat.providers.registry import scan_providers


@dataclass(frozen=True)
class LanScanResult:
    result: ScanResult
    discovered: list[NodeEndpoint]
    trusted: list[TrustedNode]


def scan_lan(
    filters: ScanFilters,
    *,
    identity: NodeIdentity,
    discovery_timeout: float = 2.0,
    include_local: bool = True,
) -> LanScanResult:
    statuses = []
    sessions = []
    warnings = []

    if include_local:
        local_result = scan_providers(filters)
        apply_node_identity(local_result.sessions, identity)
        statuses.extend(local_result.statuses)
        sessions.extend(local_result.sessions)
        warnings.extend(local_result.warnings)

    trusted = load_trusted_nodes()
    try:
        discovered = discover_nodes(timeout=discovery_timeout)
    except DiscoveryUnavailable as exc:
        discovered = []
        warnings.append(str(exc))

    discovered_by_id = {endpoint.node_id: endpoint for endpoint in discovered}
    for trusted_node in trusted:
        if trusted_node.node_id == identity.node_id:
            continue
        endpoint = discovered_by_id.get(trusted_node.node_id) or trusted_node.to_endpoint()
        token = trusted_node.token()
        if trusted_node.token_env and token is None:
            warnings.append(f"{trusted_node.name}: token env {trusted_node.token_env} is not set")
            continue
        try:
            remote = fetch_remote_snapshot(endpoint, filters, token=token)
        except RuntimeError as exc:
            warnings.append(str(exc))
            continue
        statuses.extend(remote.result.statuses)
        sessions.extend(remote.result.sessions)
        warnings.extend(f"{remote.node.name}: {warning}" for warning in remote.result.warnings)

    return LanScanResult(
        result=ScanResult(statuses=statuses, sessions=sessions, warnings=warnings),
        discovered=discovered,
        trusted=trusted,
    )
