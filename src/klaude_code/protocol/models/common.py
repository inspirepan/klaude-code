from typing import Literal

RoleType = Literal["system", "developer", "user", "assistant", "tool"]
AssistantPhase = Literal["commentary", "final_answer"]
StopReason = Literal["stop", "length", "tool_use", "error", "aborted"]
ToolStatus = Literal["success", "error", "aborted"]
TodoStatusType = Literal["pending", "in_progress", "completed"]

__all__ = [
    "AssistantPhase",
    "RoleType",
    "StopReason",
    "TodoStatusType",
    "ToolStatus",
]
