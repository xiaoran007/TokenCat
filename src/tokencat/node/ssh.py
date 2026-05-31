from __future__ import annotations

import json
import shlex
import subprocess

from tokencat.core.models import ProviderName, ScanFilters
from tokencat.core.serialize import serialize_datetime
from tokencat.node.client import NodeEndpoint, RemoteScan
from tokencat.node.snapshot import scan_result_from_snapshot

DEFAULT_REMOTE_COMMAND = "tokencat snapshot --json"


def fetch_ssh_snapshot(
    ssh_host: str,
    filters: ScanFilters,
    *,
    timeout: float = 15.0,
    remote_command: str | None = None,
) -> RemoteScan:
    command = build_ssh_snapshot_command(ssh_host, filters, remote_command=remote_command)
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"{ssh_host}: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{ssh_host}: invalid snapshot JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{ssh_host}: invalid snapshot JSON")
    node, result = scan_result_from_snapshot(payload)
    endpoint = NodeEndpoint(
        node_id=node.node_id,
        name=node.name,
        base_url=f"ssh://{ssh_host}",
        version=node.version,
        api_version=node.api_version,
        auth="ssh",
    )
    return RemoteScan(endpoint=endpoint, node=node, result=result)


def build_ssh_snapshot_command(
    ssh_host: str,
    filters: ScanFilters,
    *,
    remote_command: str | None = None,
) -> list[str]:
    remote_shell_command = shlex.join(_remote_snapshot_args(filters, remote_command=remote_command))
    return ["ssh", "-o", "BatchMode=yes", ssh_host, _login_shell_command(remote_shell_command)]


def _login_shell_command(command: str) -> str:
    quoted_command = shlex.quote(command)
    return f'if [ -n "$SHELL" ]; then exec "$SHELL" -lc {quoted_command}; else exec sh -c {quoted_command}; fi'


def _remote_snapshot_args(filters: ScanFilters, *, remote_command: str | None) -> list[str]:
    args = shlex.split(remote_command or DEFAULT_REMOTE_COMMAND)
    args.extend(_filter_args(filters))
    return args


def _filter_args(filters: ScanFilters) -> list[str]:
    args: list[str] = []
    if filters.providers:
        for provider in sorted(filters.providers, key=lambda item: item.value):
            args.extend(["--provider", provider.value if isinstance(provider, ProviderName) else str(provider)])
    if filters.since is not None:
        args.extend(["--since", serialize_datetime(filters.since) or ""])
    if filters.until is not None:
        args.extend(["--until", serialize_datetime(filters.until) or ""])
    return args
