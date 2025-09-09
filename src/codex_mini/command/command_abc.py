from abc import ABC, abstractmethod
from typing import Any

from codex_mini.protocol.events import Event


class CommandABC(ABC):
    """Abstract base class for slash commands."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Command name without the leading slash."""
        pass

    @property
    @abstractmethod
    def summary(self) -> str:
        """Brief description of what this command does."""
        pass

    @abstractmethod
    async def run(self, raw: str, session_id: str | None) -> tuple[dict[str, Any] | None, list[Event]]:
        """
        Execute the command.

        Args:
            raw: The full command string as typed by user (e.g., "/help" or "/model gpt-4")
            session_id: Current session ID, may be None if no session initialized yet

        Returns:
            operation_data: Dictionary to submit to executor, or None if no operation needed
            events: List of UI events to display immediately
        """
        pass
