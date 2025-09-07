from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import override

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from .input_abc import InputProviderABC

kb = KeyBindings()


@kb.add("enter")
def _(event):  # type: ignore
    if len(event.current_buffer.text.strip()) == 0:  # type: ignore
        event.current_buffer.insert_text("\n")  # type: ignore
        return
    event.current_buffer.validate_and_handle()  # type: ignore


@kb.add("c-j")
def _(event):  # type: ignore
    event.current_buffer.insert_text("\n")  # type: ignore


class PromptToolkitInput(InputProviderABC):
    def __init__(self, prompt: str = "┃ "):
        project = str(Path.cwd()).strip("/").replace("/", "-")
        history_path = Path.home() / ".config" / "codex-mini" / "project" / f"{project}" / "input_history.txt"

        if not history_path.parent.exists():
            history_path.parent.mkdir(parents=True, exist_ok=True)
        if not history_path.exists():
            history_path.touch()

        self._session: PromptSession[str] = PromptSession(
            prompt,
            history=FileHistory(history_path),
            multiline=True,
            prompt_continuation=prompt,
            key_bindings=kb,
            erase_when_done=True,
        )

    async def start(self) -> None:  # noqa: D401
        # No setup needed for prompt_toolkit session
        pass

    async def stop(self) -> None:  # noqa: D401
        # No teardown needed
        pass

    @override
    async def iter_inputs(self) -> AsyncIterator[str]:
        while True:
            line: str = await self._session.prompt_async()
            yield line
