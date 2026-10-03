import json
import sqlite3
import time
from pathlib import Path

import pytest

import tokencat.cli as shared_cli
from tokencat.core.time import _local_timezone

TIME = 1_790_942_400_000  # 2026-10-02 12:00 UTC
PRIVATE_ID = "PRIVATE_SESSION_IDENTIFIER"
PRIVATE_BODY = "PRIVATE_CONVERSATION_BODY"


def write_rows(home: Path, name: str, rows: list[dict]):
    path = home / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def claude_row(message="claude-message", output=50):
    return {"type": "assistant", "sessionId": PRIVATE_ID, "timestamp": "2026-10-02T12:00:00Z",
            "cwd": "/PRIVATE_PROJECT", "message": {"id": message, "role": "assistant",
            "model": "claude-sonnet-4-6", "content": [{"type": "text", "text": PRIVATE_BODY}],
            "usage": {"input_tokens": 100, "cache_read_input_tokens": 900,
                      "cache_creation_input_tokens": 0, "output_tokens": output}}}


def varint(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def number(tag, value):
    return varint(tag << 3) + varint(value)


def blob(tag, value):
    return varint((tag << 3) | 2) + varint(len(value)) + value


@pytest.fixture
def source_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    write_rows(home, f".claude/projects/example/{PRIVATE_ID}.jsonl", [claude_row()])
    return home


@pytest.fixture(autouse=True)
def local_cli_environment(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    _local_timezone.cache_clear()
    monkeypatch.setattr(shared_cli, "check_latest_version", lambda version: None)
    yield
    monkeypatch.undo()
    time.tzset()
    _local_timezone.cache_clear()


@pytest.fixture
def all_sources(source_home):
    home = source_home
    write_rows(home, ".codex/sessions/task.jsonl", [
        {"type": "session_meta", "timestamp": "2026-10-02T12:00:00Z",
         "payload": {"id": PRIVATE_ID, "cwd": "/PRIVATE_PROJECT", "model_provider": "openai"}},
        {"type": "token_usage_record", "timestamp": "2026-10-02T12:00:00Z",
         "payload": {"thread_id": PRIVATE_ID, "response_id": "codex-message", "model": "gpt-5.4",
                     "usage": {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 50,
                               "reasoning_output_tokens": 20, "total_tokens": 150}}},
    ])
    root = home / ".local/share/opencode"
    root.mkdir(parents=True)
    with sqlite3.connect(root / "opencode.db") as db:
        db.executescript("""
            CREATE TABLE session(id TEXT PRIMARY KEY,parent_id TEXT,directory TEXT,time_created INTEGER);
            CREATE TABLE message(id TEXT PRIMARY KEY,session_id TEXT,time_created INTEGER,time_updated INTEGER,data TEXT);
            CREATE TABLE part(id TEXT PRIMARY KEY,message_id TEXT,session_id TEXT,time_created INTEGER,time_updated INTEGER,data TEXT);
        """)
        db.execute("INSERT INTO session VALUES(?,NULL,'/PRIVATE_PROJECT',?)", (PRIVATE_ID, TIME))
        data = {"role": "assistant", "modelID": "gpt-5.4", "providerID": "openai",
                "time": {"created": TIME, "completed": TIME + 100}, "content": [{"text": PRIVATE_BODY}],
                "tokens": {"input": 100, "output": 50, "reasoning": 20, "cache": {"read": 80, "write": 0}}}
        db.execute("INSERT INTO message VALUES(?,?,?,?,?)", ("opencode-message", PRIVATE_ID, TIME, TIME, json.dumps(data)))
    root = home / ".gemini/antigravity/conversations"
    root.mkdir(parents=True)
    with sqlite3.connect(root / f"{PRIVATE_ID}.db") as db:
        db.executescript("""
            CREATE TABLE gen_metadata(idx INTEGER PRIMARY KEY,data BLOB,size INTEGER);
            CREATE TABLE steps(idx INTEGER PRIMARY KEY,metadata BLOB,step_payload BLOB);
        """)
        counters = (number(1, 1234) + number(2, 100) + number(3, 50) + number(5, 900)
                    + number(6, 24) + number(9, 20) + number(10, 30) + blob(11, b"antigravity-request"))
        timestamp = number(1, TIME // 1000)
        chat = (blob(1, PRIVATE_BODY.encode()) + blob(4, counters)
                + blob(19, b"gemini-3.1-pro-preview") + blob(9, blob(4, timestamp)))
        generation = blob(1, chat)
        db.execute("INSERT INTO gen_metadata VALUES(1,?,?)", (generation, len(generation)))
    return home
