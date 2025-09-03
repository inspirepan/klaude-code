from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from .input_abc import InputProvider


class PromptToolkitInput(InputProvider):
    def __init__(self, prompt: str = "┃ "):
        project = str(Path.cwd()).strip("/").replace("/", "-")
        history_path = (
            Path.home()
            / ".config"
            / "codex-minimal"
            / "project"
            / f"{project}"
            / "input_history.txt"
        )

        if not history_path.parent.exists():
            history_path.parent.mkdir(parents=True, exist_ok=True)
        if not history_path.exists():
            history_path.touch()

        self._session: PromptSession[str] = PromptSession(
            prompt, history=FileHistory(history_path)
        )

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
