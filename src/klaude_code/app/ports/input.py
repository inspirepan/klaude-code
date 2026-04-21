from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from klaude_code.protocol.message import UserInputPayload


class InputProviderABC(ABC):
    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    @abstractmethod
    async def iter_inputs(self) -> AsyncIterator[UserInputPayload]:
        raise NotImplementedError
        yield UserInputPayload(text="")

    def set_prompt_suggestion(self, text: str | None) -> None:
        """Push a predicted-next-prompt into the input layer.

        When ``text`` is non-empty and the buffer is empty, the provider should
        surface it as a placeholder and let the user accept it (e.g. Enter on
        an empty buffer submits as ``text``; Tab pre-fills the buffer).
        ``None`` clears any currently displayed suggestion.

        Optional: providers that don't support inline suggestions can no-op.
        """
        del text
