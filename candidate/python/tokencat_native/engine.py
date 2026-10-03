from __future__ import annotations

import importlib
import json


class Engine:
    def __init__(self, configuration: dict):
        try:
            native = importlib.import_module("tokencat_native._native")
        except ImportError as exc:
            raise RuntimeError(
                "Cannot load the native candidate extension. Install tokencat-native "
                "from a compatible wheel or compile the candidate source with Rust. "
                f"Loader error: {exc}"
            ) from exc
        self._engine = native.Engine(json.dumps(configuration))

    def scan(self) -> dict:
        return json.loads(self._engine.scan())

    def query(self, query: dict) -> dict:
        dashboard = json.loads(self._engine.query(json.dumps(query)))
        if dashboard["schema_version"] != 1:
            raise RuntimeError(f"Unsupported native dashboard schema: {dashboard['schema_version']}")
        return dashboard

    def close(self) -> None:
        self._engine.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def public_dashboard(snapshot: dict) -> dict:
    """Export dashboard usage, excluding internal identifiers and observed-state metadata."""
    payload = {key: value for key, value in snapshot.items() if key != "states"}
    labels = {row["id"]: row["label"] for row in snapshot["sessions"]}
    payload["sessions"] = [
        {**row, "id": row["label"], "parent_id": labels.get(row["parent_id"])}
        for row in snapshot["sessions"]
    ]
    return payload
