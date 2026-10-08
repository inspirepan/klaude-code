from typing import Literal

from pydantic import BaseModel


class ShellTaskSnapshot(BaseModel):
    task_id: str
    session_id: str
    command: str
    description: str
    work_dir: str
    status: Literal["running", "stopping", "completed", "failed", "stopped", "timed_out", "lost"]
    background: bool
    started_at: float
    ended_at: float | None = None
    exit_code: int | None = None
    output_path: str
    reason: str | None = None
    pid: int | None = None
    output_expired: bool = False


class ShellTaskOutput(BaseModel):
    task: ShellTaskSnapshot
    output: str
    next_offset: int
    truncated: bool
