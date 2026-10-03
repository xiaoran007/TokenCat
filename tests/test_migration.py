import sqlite3

import pytest
from typer.testing import CliRunner

from tokencat.cli import app
from tokencat.dashboard import configuration
from tokencat.engine import Engine, migrate_candidate_ledger
from conftest import PRIVATE_ID, claude_row, write_rows


def candidate_ledger(home):
    path = home / ".tokencat-candidate/usage.sqlite3"
    with Engine({**configuration(home), "database_path": str(path)}) as engine:
        engine.scan()
    return path


def total(home):
    with Engine(configuration(home)) as engine:
        return engine.query({"since_ms": 1_790_899_200_000, "until_ms": 1_790_985_600_000,
                             "timezone": "UTC"})["summary"]["cost"]["total_tokens"]


def test_first_official_run_keeps_candidate_history_and_committed_wal(source_home):
    original = candidate_ledger(source_home)
    (source_home / f".claude/projects/example/{PRIVATE_ID}.jsonl").unlink()
    connection = sqlite3.connect(original)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE migration_probe(value TEXT)")
        connection.execute("INSERT INTO migration_probe VALUES('committed')")
        connection.commit()
        assert original.with_name(original.name + "-wal").exists()
        result = CliRunner().invoke(app, ["--since", "2026-10-02", "--until", "2026-10-02", "--json"])
        assert result.exit_code == 0, result.output
        assert total(source_home) == 1050
        migrated = source_home / ".tokencat/usage.sqlite3"
        with sqlite3.connect(migrated) as database:
            assert database.execute("SELECT value FROM migration_probe").fetchone() == ("committed",)
        assert original.exists()
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone() == (1,)
    finally:
        connection.close()


def test_existing_official_ledger_is_never_overwritten(source_home):
    original = candidate_ledger(source_home)
    write_rows(source_home, f".claude/projects/example/{PRIVATE_ID}.jsonl", [claude_row(), claude_row("second")])
    with Engine(configuration(source_home)) as engine:
        engine.scan()
    migrate_candidate_ledger(source_home)
    assert total(source_home) == 2100
    assert original.exists()


def test_corrupt_candidate_is_an_error_and_does_not_publish_partial_ledger(source_home):
    path = source_home / ".tokencat-candidate/usage.sqlite3"
    path.parent.mkdir()
    path.write_bytes(b"invalid SQLite ledger")
    with pytest.raises(RuntimeError, match="Cannot migrate"):
        migrate_candidate_ledger(source_home)
    assert not (source_home / ".tokencat/usage.sqlite3").exists()
    assert list((source_home / ".tokencat").iterdir()) == []
    assert path.read_bytes() == b"invalid SQLite ledger"
    result = CliRunner().invoke(app, ["--json"])
    assert result.exit_code == 1
    assert "Cannot migrate the candidate usage ledger" in result.output


def test_concurrent_publication_keeps_the_first_official_ledger(source_home, monkeypatch):
    import tokencat.engine as module
    candidate_ledger(source_home)
    def concurrent_cli(temporary, destination):
        with sqlite3.connect(destination) as database:
            database.execute("CREATE TABLE concurrent_probe(value INTEGER)")
            database.execute("INSERT INTO concurrent_probe VALUES(42)")
        raise FileExistsError("concurrent CLI published first")
    monkeypatch.setattr(module.os, "link", concurrent_cli)
    migrate_candidate_ledger(source_home)
    with sqlite3.connect(source_home / ".tokencat/usage.sqlite3") as database:
        assert database.execute("SELECT value FROM concurrent_probe").fetchone() == (42,)
    assert not list((source_home / ".tokencat").glob(".usage-*.sqlite3"))
