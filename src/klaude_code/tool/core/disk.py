"""Atomic durable task snapshots shared by task executors."""

import os
from pathlib import Path
from uuid import uuid4


def write_snapshot(directory: Path, task_id: str, payload: str) -> None:
    path = directory / f"{task_id}.json"
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8") as writer:
        writer.write(payload)
        writer.flush()
        os.fsync(writer.fileno())
    temporary.replace(path)
    if os.name == "posix":
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
