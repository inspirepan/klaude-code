from abc import ABC, abstractmethod

from pydantic import BaseModel

from klaude_code.core import Agent
from klaude_code.protocol.commands import CommandName
from klaude_code.protocol.events import (DeveloperMessageEvent,
                                         ReplayHistoryEvent, WelcomeEvent)


class CommandResult(BaseModel):
    """Result of a command execution."""

    agent_input: str | None = None  # Input to be submitted to agent, or None if no input needed
    events: list[DeveloperMessageEvent | WelcomeEvent | ReplayHistoryEvent] | None = (
        None  # List of UI events to display immediately
    )


class CommandABC(ABC):
    """Abstract base class for slash commands."""

    @property
    @abstractmethod
    def name(self) -> CommandName | str:
        """Command name without the leading slash."""
        pass

    @property
    @abstractmethod
    def summary(self) -> str:
        """Brief description of what this command does."""
        pass

    @property
    def is_interactive(self) -> bool:
        """Whether this command is interactive."""
        return False

    @property
    def support_addition_params(self) -> bool:
        """Whether this command support additional parameters."""
        return False

    @abstractmethod
    async def run(self, raw: str, agent: Agent) -> CommandResult:
        """
        Execute the command.

        Args:
            raw: The full command string as typed by user (e.g., "/help" or "/model gpt-4")
            session_id: Current session ID, may be None if no session initialized yet

        Returns:
            CommandResult: Result of the command execution
        """
        pass
