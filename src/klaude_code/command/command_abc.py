from abc import ABC, abstractmethod
from enum import Enum
from typing import Protocol

from pydantic import BaseModel

from klaude_code.llm import LLMClientABC
from klaude_code.protocol import commands, llm_param
from klaude_code.protocol import events as protocol_events
from klaude_code.session.session import Session


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


class InputActionType(str, Enum):
    """Supported input action kinds."""

    RUN_AGENT = "run_agent"
    CHANGE_MODEL = "change_model"
    CLEAR = "clear"


class InputAction(BaseModel):
    """Structured executor action derived from a user input."""

    type: InputActionType
    text: str = ""
    model_name: str | None = None

    @classmethod
    def run_agent(cls, text: str) -> "InputAction":
        """Create a RunAgent action preserving the provided text."""

        return cls(type=InputActionType.RUN_AGENT, text=text)

    @classmethod
    def change_model(cls, model_name: str) -> "InputAction":
        """Create a ChangeModel action for the provided model name."""

        return cls(type=InputActionType.CHANGE_MODEL, model_name=model_name)

    @classmethod
    def clear(cls) -> "InputAction":
        """Create a Clear action to reset the session."""

        return cls(type=InputActionType.CLEAR)


class CommandResult(BaseModel):
    """Result of a command execution."""

    events: (
        list[protocol_events.DeveloperMessageEvent | protocol_events.WelcomeEvent | protocol_events.ReplayHistoryEvent]
        | None
    ) = None  # List of UI events to display immediately
    actions: list[InputAction] | None = None


class CommandABC(ABC):
    """Abstract base class for slash commands."""

    @property
    @abstractmethod
    def name(self) -> commands.CommandName | str:
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
        return "additional instructions"

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
