from __future__ import annotations

from typing import Literal

from klaude_code.protocol import model

from .base import ResponseEvent


class ToolCallEvent(ResponseEvent):
    tool_call_id: str
    tool_name: str
    arguments: str


class ToolResultEvent(ResponseEvent):
    tool_call_id: str
    tool_name: str
    result: str
    ui_extra: model.ToolResultUIExtra | None = None
    status: Literal["success", "error", "aborted"]
    task_metadata: model.TaskMetadata | None = None
    is_last_in_turn: bool = True

    @property
    def is_error(self) -> bool:
        return self.status in ("error", "aborted")
