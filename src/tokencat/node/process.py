from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

NODE_RUNTIME_DIR = Path("~/.tokencat").expanduser()
NODE_PID_PATH = NODE_RUNTIME_DIR / "node.pid"
NODE_LOG_PATH = NODE_RUNTIME_DIR / "logs" / "node.log"


@dataclass(frozen=True)
class NodeProcessStatus:
    pid: int | None
    running: bool
    pid_path: Path
    log_path: Path


def start_detached_node(args: list[str], *, pid_path: Path = NODE_PID_PATH, log_path: Path = NODE_LOG_PATH) -> NodeProcessStatus:
    current = read_node_status(pid_path=pid_path, log_path=log_path)
    if current.running:
        return current

    pid_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "tokencat", "serve", "--foreground", *args]
    with log_path.open("ab") as log_handle:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    return NodeProcessStatus(pid=process.pid, running=True, pid_path=pid_path, log_path=log_path)


def read_node_status(*, pid_path: Path = NODE_PID_PATH, log_path: Path = NODE_LOG_PATH) -> NodeProcessStatus:
    pid = _read_pid(pid_path)
    running = _pid_is_running(pid) if pid is not None else False
    return NodeProcessStatus(pid=pid, running=running, pid_path=pid_path, log_path=log_path)


def stop_detached_node(*, pid_path: Path = NODE_PID_PATH, log_path: Path = NODE_LOG_PATH) -> NodeProcessStatus:
    status = read_node_status(pid_path=pid_path, log_path=log_path)
    if status.pid is None:
        return status
    if status.running:
        os.kill(status.pid, signal.SIGTERM)
    try:
        pid_path.unlink()
    except FileNotFoundError:
        pass
    return read_node_status(pid_path=pid_path, log_path=log_path)


def _read_pid(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _pid_is_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
