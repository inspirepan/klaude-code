from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class InputProviderABC(ABC):
    @abstractmethod
    async def start(self) -> None:
        """Optional setup before reading inputs."""

    @abstractmethod
    async def stop(self) -> None:
        """Optional teardown when stopping."""

    @abstractmethod
    def iter_inputs(self) -> AsyncIterator[str]:
        """Return an async iterator of user inputs."""
        ...
