from abc import ABC, abstractmethod
from typing import Protocol

from pydantic import BaseModel

from klaude_code.llm import LLMClientABC
from klaude_code.protocol import events as protocol_events
from klaude_code.protocol import llm_param, message, op
from klaude_code.session.session import Session

from .types import CommandName


class AgentProfile(Protocol):
    """Protocol for the agent's active model profile."""

    @property
    def llm_client(self) -> LLMClientABC: ...

    @property
    def system_prompt(self) -> str | None: ...

    @property
    def tools(self) -> list[llm_param.ToolSchema]: ...


class Agent(Protocol):
    """Protocol for Agent objects passed to commands."""

    session: Session

    @property
    def profile(self) -> AgentProfile | None: ...

    def get_llm_client(self) -> LLMClientABC: ...


class WebModeRequest(BaseModel):
    """Request to leave TUI and start the web server mode."""

    host: str = "127.0.0.1"
    port: int = 8765
    no_open: bool = False
    debug: bool | None = None


class CommandResult(BaseModel):
    """Result of a command execution."""

    events: (
        list[
            protocol_events.NoticeEvent
            | protocol_events.ErrorEvent
            | protocol_events.WelcomeEvent
            | protocol_events.ReplayHistoryEvent
            | protocol_events.SessionStatsEvent
            | protocol_events.ModelChangedEvent
            | protocol_events.ThinkingChangedEvent
            | protocol_events.SubAgentModelChangedEvent
            | protocol_events.CompactModelChangedEvent
        ]
        | None
    ) = None  # List of UI events to display immediately
    operations: list[op.Operation] | None = None
    web_mode_request: WebModeRequest | None = None


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

    @property
    def placeholder(self) -> str:
        """Placeholder text for additional parameters in help display."""
        return "instructions"

    @abstractmethod
    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        """
        Execute the command.

        Args:
            agent: The agent instance
            user_input: User input with text containing command arguments (without command name)

        Returns:
            CommandResult: Result of the command execution
        """
        pass
