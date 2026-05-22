from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from tokencat.node.identity import NodeIdentity
from tokencat.node.protocol import filters_from_snapshot_request
from tokencat.node.snapshot import build_snapshot_payload
from tokencat.providers.registry import scan_providers


class TokenCatHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        identity: NodeIdentity,
        token: str | None,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.identity = identity
        self.token = token


def build_handler() -> type[BaseHTTPRequestHandler]:
    class SnapshotRequestHandler(BaseHTTPRequestHandler):
        server: TokenCatHTTPServer

        def do_GET(self) -> None:
            if self.path == "/v1/health":
                self._write_json({"ok": True})
                return
            if self.path == "/v1/node":
                self._write_json({
                    "node": self.server.identity.to_dict(),
                    "auth": "token" if self.server.token else "none",
                })
                return
            self._write_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if self.path != "/v1/snapshot":
                self._write_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            if not self._authorized():
                self._write_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
                return

            try:
                request_payload = self._read_json()
                filters = filters_from_snapshot_request(request_payload)
                include_paths = bool(request_payload.get("include_paths"))
                include_titles = bool(request_payload.get("include_titles"))
                result = scan_providers(filters)
                payload = build_snapshot_payload(
                    identity=self.server.identity,
                    filters=filters,
                    result=result,
                    include_paths=include_paths,
                    include_titles=include_titles,
                )
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return

            self._write_json(payload)

        def log_message(self, format: str, *args) -> None:
            return

        def _authorized(self) -> bool:
            token = self.server.token
            if not token:
                return True
            return self.headers.get("Authorization") == f"Bearer {token}"

        def _read_json(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object")
            return payload

        def _write_json(self, payload: object, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return SnapshotRequestHandler


def serve_forever(
    *,
    host: str,
    port: int,
    identity: NodeIdentity,
    token: str | None,
    on_ready: Callable[[TokenCatHTTPServer], None] | None = None,
) -> None:
    server = TokenCatHTTPServer((host, port), build_handler(), identity=identity, token=token)
    if on_ready is not None:
        on_ready(server)
    try:
        server.serve_forever()
    finally:
        server.server_close()
