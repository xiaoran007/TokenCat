from __future__ import annotations

import socket
import time
from dataclasses import dataclass

from tokencat.node.client import NodeEndpoint
from tokencat.node.identity import NodeIdentity

SERVICE_TYPE = "_tokencat._tcp.local."


class DiscoveryUnavailable(RuntimeError):
    pass


@dataclass
class ServiceRegistration:
    zeroconf: object
    info: object

    def close(self) -> None:
        self.zeroconf.unregister_service(self.info)
        self.zeroconf.close()


def register_service(
    *,
    identity: NodeIdentity,
    host: str,
    port: int,
    auth: str,
) -> ServiceRegistration:
    zeroconf_mod = _import_zeroconf()
    advertised_host = _advertised_host(host)
    service_name = f"{identity.name}-{identity.short_id}.{SERVICE_TYPE}"
    properties = {
        "node_id": identity.node_id,
        "name": identity.name,
        "version": identity.version,
        "api": str(identity.api_version),
        "auth": auth,
        "schema": "1",
    }
    info = zeroconf_mod.ServiceInfo(
        SERVICE_TYPE,
        service_name,
        addresses=[socket.inet_aton(advertised_host)],
        port=port,
        properties=properties,
        server=f"{identity.name}.local.",
    )
    zeroconf = zeroconf_mod.Zeroconf()
    zeroconf.register_service(info)
    return ServiceRegistration(zeroconf=zeroconf, info=info)


def discover_nodes(*, timeout: float = 2.0) -> list[NodeEndpoint]:
    zeroconf_mod = _import_zeroconf()
    listener = _NodeListener(zeroconf_mod)
    zeroconf = zeroconf_mod.Zeroconf()
    browser = zeroconf_mod.ServiceBrowser(zeroconf, SERVICE_TYPE, listener)
    try:
        time.sleep(timeout)
        endpoints = {endpoint.node_id: endpoint for endpoint in listener.endpoints}
        return sorted(endpoints.values(), key=lambda item: (item.name.lower(), item.node_id))
    finally:
        browser.cancel()
        zeroconf.close()


class _NodeListener:
    def __init__(self, zeroconf_mod) -> None:
        self.zeroconf_mod = zeroconf_mod
        self.endpoints: list[NodeEndpoint] = []

    def add_service(self, zeroconf, service_type: str, name: str) -> None:
        info = zeroconf.get_service_info(service_type, name)
        if info is None:
            return
        endpoint = _endpoint_from_service_info(info)
        if endpoint is not None:
            self.endpoints.append(endpoint)

    def update_service(self, zeroconf, service_type: str, name: str) -> None:
        self.add_service(zeroconf, service_type, name)

    def remove_service(self, zeroconf, service_type: str, name: str) -> None:
        return


def _endpoint_from_service_info(info) -> NodeEndpoint | None:
    properties = _decode_properties(info.properties)
    node_id = properties.get("node_id")
    name = properties.get("name")
    if not node_id or not name:
        return None
    addresses = list(getattr(info, "addresses", []) or [])
    if not addresses:
        return None
    host = socket.inet_ntoa(addresses[0])
    port = int(getattr(info, "port", 0) or 0)
    if not port:
        return None
    return NodeEndpoint(
        node_id=node_id,
        name=name,
        base_url=f"http://{host}:{port}",
        host=host,
        port=port,
        version=properties.get("version"),
        api_version=int(properties.get("api") or 1),
        auth=properties.get("auth") or "none",
    )


def _decode_properties(raw: dict[bytes, bytes]) -> dict[str, str]:
    properties: dict[str, str] = {}
    for key, value in raw.items():
        properties[key.decode("utf-8")] = value.decode("utf-8")
    return properties


def _advertised_host(host: str) -> str:
    if host not in {"", "0.0.0.0", "::"}:
        return host
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())
    finally:
        sock.close()


def _import_zeroconf():
    try:
        import zeroconf
    except ImportError as exc:
        raise DiscoveryUnavailable("LAN discovery requires the zeroconf package. Reinstall TokenCat with current dependencies.") from exc
    return zeroconf
