from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from tokencat.core.models import ProviderStatus, ScanFilters, ScanResult, SessionRecord
from tokencat.node.client import NodeEndpoint, RemoteScan, fetch_remote_snapshot
from tokencat.node.discovery import DiscoveryUnavailable, discover_nodes
from tokencat.node.identity import NodeIdentity, apply_node_identity
from tokencat.node.ssh import fetch_ssh_snapshot
from tokencat.node.trust import TrustedNode, load_trusted_nodes
from tokencat.providers.registry import scan_providers

LAN_SCAN_MAX_WORKERS = 16


@dataclass(frozen=True)
class LanScanResult:
    result: ScanResult
    discovered: list[NodeEndpoint]
    trusted: list[TrustedNode]


@dataclass(frozen=True)
class _TrustedScanResult:
    statuses: list[ProviderStatus]
    sessions: list[SessionRecord]
    warnings: list[str]


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
    for remote_result in _scan_trusted_nodes(filters, trusted, identity=identity, discovered_by_id=discovered_by_id):
        statuses.extend(remote_result.statuses)
        sessions.extend(remote_result.sessions)
        warnings.extend(remote_result.warnings)

    return LanScanResult(
        result=ScanResult(statuses=statuses, sessions=sessions, warnings=warnings),
        discovered=discovered,
        trusted=trusted,
    )


def _scan_trusted_nodes(
    filters: ScanFilters,
    trusted: list[TrustedNode],
    *,
    identity: NodeIdentity,
    discovered_by_id: dict[str, NodeEndpoint],
) -> list[_TrustedScanResult]:
    remote_nodes = [trusted_node for trusted_node in trusted if trusted_node.node_id != identity.node_id]
    if not remote_nodes:
        return []
    if len(remote_nodes) == 1:
        return [_scan_trusted_node(remote_nodes[0], filters, discovered_by_id=discovered_by_id)]

    max_workers = min(len(remote_nodes), LAN_SCAN_MAX_WORKERS)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(
            executor.map(
                lambda trusted_node: _scan_trusted_node(trusted_node, filters, discovered_by_id=discovered_by_id),
                remote_nodes,
            )
        )


def _scan_trusted_node(
    trusted_node: TrustedNode,
    filters: ScanFilters,
    *,
    discovered_by_id: dict[str, NodeEndpoint],
) -> _TrustedScanResult:
    if trusted_node.transport == "ssh":
        if not trusted_node.ssh_host:
            return _TrustedScanResult(statuses=[], sessions=[], warnings=[f"{trusted_node.name}: missing ssh host"])
        try:
            remote = fetch_ssh_snapshot(
                trusted_node.ssh_host,
                filters,
                remote_command=trusted_node.remote_command,
            )
        except RuntimeError as exc:
            return _TrustedScanResult(statuses=[], sessions=[], warnings=[str(exc)])
        return _remote_scan_result(remote)

    endpoint = discovered_by_id.get(trusted_node.node_id) or trusted_node.to_endpoint()
    token = trusted_node.token()
    if trusted_node.token_env and token is None:
        return _TrustedScanResult(
            statuses=[],
            sessions=[],
            warnings=[f"{trusted_node.name}: token env {trusted_node.token_env} is not set"],
        )
    try:
        remote = fetch_remote_snapshot(endpoint, filters, token=token)
    except RuntimeError as exc:
        return _TrustedScanResult(statuses=[], sessions=[], warnings=[str(exc)])
    return _remote_scan_result(remote)


def _remote_scan_result(remote: RemoteScan) -> _TrustedScanResult:
    return _TrustedScanResult(
        statuses=list(remote.result.statuses),
        sessions=list(remote.result.sessions),
        warnings=[f"{remote.node.name}: {warning}" for warning in remote.result.warnings],
    )
