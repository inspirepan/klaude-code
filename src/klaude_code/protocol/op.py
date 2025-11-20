"""
Operation protocol for the executor system.

This module defines the operation types and submission structure
that the executor uses to handle different types of requests.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from klaude_code.core.executor import ExecutorContext


class OperationType(Enum):
    """Enumeration of supported operation types."""

    USER_INPUT = "user_input"
    INTERRUPT = "interrupt"
    INIT_AGENT = "init_agent"
    END = "end"


class Operation(BaseModel, ABC):
    """Base class for all operations that can be submitted to the executor."""

    type: OperationType
    id: str = Field(default_factory=lambda: uuid4().hex)

    @abstractmethod
    async def execute(self, context: "ExecutorContext") -> None:
        """Execute this operation within the given executor context."""
        pass


class UserInputOperation(Operation):
    """Operation for handling user text input that should be processed by an agent."""

    type: OperationType = OperationType.USER_INPUT
    content: str
    session_id: str | None = None

    async def execute(self, context: "ExecutorContext") -> None:
        """Execute user input by running it through an agent."""
        await context.handle_user_input(self)


class InterruptOperation(Operation):
    """Operation for interrupting currently running tasks."""

    type: OperationType = OperationType.INTERRUPT
    target_session_id: str | None = None  # If None, interrupt all sessions

    async def execute(self, context: "ExecutorContext") -> None:
        """Execute interrupt by cancelling active tasks."""
        await context.handle_interrupt(self)


class InitAgentOperation(Operation):
    """Operation for initializing an agent and replaying history if any."""

    type: OperationType = OperationType.INIT_AGENT
    session_id: str | None = None

    async def execute(self, context: "ExecutorContext") -> None:
        await context.handle_init_agent(self)


class EndOperation(Operation):
    """Operation for gracefully stopping the executor."""

    type: OperationType = OperationType.END

    async def execute(self, context: "ExecutorContext") -> None:
        """Execute end operation - this is a no-op, just signals the executor to stop."""
        pass


class Submission(BaseModel):
    """A submission represents a request sent to the executor for processing."""

    id: str
    operation: Operation
