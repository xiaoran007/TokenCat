from __future__ import annotations

import importlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


class Engine:
    def __init__(self, configuration: dict):
        try:
            native = importlib.import_module("tokencat._native")
        except ImportError as exc:
            raise RuntimeError(
                "Cannot load the native extension. Install tokencat "
                "from a compatible wheel or compile the source with Rust. "
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


def migrate_candidate_ledger(home: Path) -> None:
    """Copy the candidate ledger once, including committed WAL data; keep the original."""
    database = home / ".tokencat/usage.sqlite3"
    candidate = home / ".tokencat-candidate/usage.sqlite3"
    if database.exists() or not candidate.exists():
        return
    database.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".usage-", suffix=".sqlite3", dir=database.parent)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(candidate.as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(temporary)) as target:
                source.backup(target)
        try:
            # Publish atomically without replacing a ledger created by another CLI invocation.
            os.link(temporary, database)
        except FileExistsError:
            pass
    except sqlite3.Error as exc:
        raise RuntimeError(f"Cannot migrate the candidate usage ledger: {exc}") from exc
    finally:
        Path(temporary).unlink()
