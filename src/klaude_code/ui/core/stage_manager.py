from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum


class Stage(Enum):
    WAITING = "waiting"
    THINKING = "thinking"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


class StageManager:
    """Manage display stage transitions and invoke lifecycle callbacks."""

    def __init__(
        self,
        *,
        finish_assistant: Callable[[], Awaitable[None]],
        finish_thinking: Callable[[], Awaitable[None]],
    ):
        self._stage = Stage.WAITING
        self._finish_assistant = finish_assistant
        self._finish_thinking = finish_thinking

    @property
    def current_stage(self) -> Stage:
        return self._stage

    async def transition_to(self, new_stage: Stage) -> None:
        if self._stage == new_stage:
            return
        await self._leave_current_stage()
        self._stage = new_stage

    async def enter_thinking_stage(self) -> None:
        if self._stage == Stage.THINKING:
            return
        await self.transition_to(Stage.THINKING)

    async def finish_assistant(self) -> None:
        if self._stage != Stage.ASSISTANT:
            await self._finish_assistant()
            return
        await self._finish_assistant()
        self._stage = Stage.WAITING

    async def _leave_current_stage(self) -> None:
        if self._stage == Stage.THINKING:
            await self._finish_thinking()
        elif self._stage == Stage.ASSISTANT:
            await self.finish_assistant()
        self._stage = Stage.WAITING
