from __future__ import annotations

from collections.abc import AsyncIterator

from prompt_toolkit import PromptSession

from .input import InputProvider


class PromptToolkitInput(InputProvider):
    def __init__(self, prompt: str = "❯ "):
        self._session: PromptSession[str] = PromptSession(prompt)

    async def start(self) -> None:  # noqa: D401
        # No setup needed for prompt_toolkit session
        pass

    async def stop(self) -> None:  # noqa: D401
        # No teardown needed
        pass

    async def iter_inputs(self) -> AsyncIterator[str]:
        while True:
            line: str = await self._session.prompt_async()
            yield line
