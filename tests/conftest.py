from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def create_codex_state_db(path: Path, rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            """
            create table threads (
                id text primary key,
                rollout_path text,
                created_at integer,
                updated_at integer,
                source text,
                model_provider text,
                cwd text,
                title text,
                sandbox_policy text,
                approval_mode text,
                tokens_used integer,
                has_user_event integer,
                archived integer,
                archived_at integer,
                git_sha text,
                git_branch text,
                git_origin_url text,
                cli_version text,
                first_user_message text,
                agent_nickname text,
                agent_role text,
                memory_mode text
            )
            """
        )
        conn.executemany(
            """
            insert into threads (
                id, rollout_path, created_at, updated_at, source, model_provider, cwd, title,
                sandbox_policy, approval_mode, tokens_used, has_user_event, archived, archived_at,
                git_sha, git_branch, git_origin_url, cli_version, first_user_message, agent_nickname,
                agent_role, memory_mode
            ) values (?, '', ?, ?, ?, ?, ?, ?, '', '', ?, 1, 0, null, '', '', '', ?, '', '', '', 'enabled')
            """,
            rows,
        )
    conn.close()


@pytest.fixture()
def sample_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home
