from __future__ import annotations

from enum import Enum


class DisplayState(Enum):
    IDLE = "idle"
    THINKING = "thinking"
    STREAMING_TEXT = "streaming_text"
    TOOL_EXECUTING = "tool_executing"
    ERROR = "error"
