from __future__ import annotations

from dataclasses import dataclass

from tokencat.node.client import NodeEndpoint
from tokencat.node.ssh_config import SSHHostCandidate
from tokencat.node.trust import TrustedNode


@dataclass(frozen=True)
class NodeCandidate:
    key: str
    name: str
    transport: str
    address: str
    auth: str
    trusted: bool = False
    endpoint: NodeEndpoint | None = None
    ssh_host: str | None = None

    @property
    def node_id(self) -> str:
        return self.key

    @property
    def base_url(self) -> str:
        return self.address

    @property
    def version(self) -> str | None:
        return self.endpoint.version if self.endpoint is not None else None


def http_candidates(endpoints: list[NodeEndpoint], trusted: list[TrustedNode]) -> list[NodeCandidate]:
    trusted_ids = {node.node_id for node in trusted}
    return [
        NodeCandidate(
            key=f"http:{endpoint.node_id}",
            name=endpoint.name,
            transport="http",
            address=endpoint.base_url,
            auth=endpoint.auth,
            trusted=endpoint.node_id in trusted_ids,
            endpoint=endpoint,
        )
        for endpoint in endpoints
    ]


def ssh_candidates(hosts: list[SSHHostCandidate], trusted: list[TrustedNode]) -> list[NodeCandidate]:
    trusted_hosts = {node.ssh_host for node in trusted if node.transport == "ssh"}
    return [
        NodeCandidate(
            key=f"ssh:{host.alias}",
            name=host.alias,
            transport="ssh",
            address=host.address,
            auth="ssh",
            trusted=host.alias in trusted_hosts,
            ssh_host=host.alias,
        )
        for host in hosts
    ]


def trusted_node_candidates(nodes: list[TrustedNode]) -> list[NodeCandidate]:
    candidates: list[NodeCandidate] = []
    for node in nodes:
        if node.transport == "ssh":
            address = node.ssh_host or "-"
            auth = "ssh"
        else:
            address = node.base_url or "-"
            auth = "token" if node.token_env else "none"
        candidates.append(
            NodeCandidate(
                key=node.node_id,
                name=node.name,
                transport=node.transport,
                address=address,
                auth=auth,
                trusted=True,
                ssh_host=node.ssh_host,
            )
        )
    return candidates
