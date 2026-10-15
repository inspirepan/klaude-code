"""Shared control contracts; executors retain ownership of live execution."""

from typing import Literal

from pydantic import BaseModel, Field

from klaude_code.protocol.models import TaskFileChange, TaskMetadata
from klaude_code.protocol.shell_task import ShellTaskSnapshot

TaskStatus = Literal["queued", "running", "stopping", "completed", "failed", "stopped", "timed_out", "lost"]
ACTIVE_TASK_STATUSES = frozenset({"queued", "running", "stopping"})
TASK_DELIVERY_ID_PREFIX = "task-result:"


class TaskReference(BaseModel):
    kind: Literal["shell", "agent"]
    owner_session_id: str
    task_id: str
    run_id: str
    session_id: str | None = None
    operation_id: str | None = None


class BackgroundTaskResult(BaseModel):
    text: str
    error: bool = False
    metadata: TaskMetadata | None = None
    file_changes: list[TaskFileChange] | None = None
    # Display-only head of `text`, kept in snapshots whose `text` is cleared.
    # Model-facing serializers exclude it via `MODEL_FACING_EXCLUDE`.
    summary: str | None = None


class BackgroundTaskSnapshot(BaseModel):
    ref: TaskReference
    status: TaskStatus
    description: str = ""
    agent_type: str | None = None
    started_at: float
    ended_at: float | None = None
    result: BackgroundTaskResult | None = None
    shell: ShellTaskSnapshot | None = None
    delivery_id: str
    delivered: bool = False
    expected_stop: bool = False
    output_unavailable: bool = False


# Drop display-only snapshot fields when a TaskResponse is serialized for the model.
MODEL_FACING_EXCLUDE = {"tasks": {"__all__": {"result": {"summary"}}}}
TASK_RESULT_SUMMARY_MAX_CHARS = 600


class TaskRequest(BaseModel):
    action: Literal["list", "output", "wait", "stop"]
    task_id: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=16384, gt=0, le=1048576)
    wait_ms: int = Field(default=10000, ge=0, le=300000)


class TaskResponse(BaseModel):
    tasks: list[BackgroundTaskSnapshot]
    output: str = ""
    next_offset: int = 0
    truncated: bool = False
    interrupted_wait: bool = False
    delivery_id: str | None = None
    output_unavailable: bool = False
