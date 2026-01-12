"""
Operation protocol for the executor system.

This module defines the operation types and submission structure
that the executor uses to handle different types of requests.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from klaude_code.protocol.llm_param import Thinking
from klaude_code.protocol.message import UserInputPayload

if TYPE_CHECKING:
    from klaude_code.protocol.op_handler import OperationHandler


class OperationType(Enum):
    """Enumeration of supported operation types."""

    RUN_AGENT = "run_agent"
    RUN_BASH = "run_bash"
    CONTINUE_AGENT = "continue_agent"
    COMPACT_SESSION = "compact_session"
    CHANGE_MODEL = "change_model"
    CHANGE_COMPACT_MODEL = "change_compact_model"
    CHANGE_SUB_AGENT_MODEL = "change_sub_agent_model"
    CHANGE_THINKING = "change_thinking"
    CLEAR_SESSION = "clear_session"
    RESUME_SESSION = "resume_session"
    EXPORT_SESSION = "export_session"
    INTERRUPT = "interrupt"
    INIT_AGENT = "init_agent"
    END = "end"


class Operation(BaseModel):
    """Base class for all operations that can be submitted to the executor."""

    type: OperationType
    id: str = Field(default_factory=lambda: uuid4().hex)

    async def execute(self, handler: OperationHandler) -> None:
        """Execute this operation using the given handler."""
        raise NotImplementedError("Subclasses must implement execute()")


class RunAgentOperation(Operation):
    """Operation for launching an agent task for a given session."""

    type: OperationType = OperationType.RUN_AGENT
    session_id: str
    input: UserInputPayload

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_run_agent(self)


class RunBashOperation(Operation):
    """Operation for running a user-entered bash-mode command."""

    type: OperationType = OperationType.RUN_BASH
    session_id: str
    command: str

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_run_bash(self)


class ContinueAgentOperation(Operation):
    """Operation for continuing an agent task without adding a new user message.

    Used for recovery after interruptions (network errors, API failures, etc.).
    """

    type: OperationType = OperationType.CONTINUE_AGENT
    session_id: str

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_continue_agent(self)


class CompactSessionOperation(Operation):
    """Operation for compacting a session's conversation history."""

    type: OperationType = OperationType.COMPACT_SESSION
    session_id: str
    reason: Literal["threshold", "overflow", "manual"]
    focus: str | None = None
    will_retry: bool = False

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_compact_session(self)


class ChangeModelOperation(Operation):
    """Operation for changing the model used by the active agent session."""

    type: OperationType = OperationType.CHANGE_MODEL
    session_id: str
    model_name: str
    save_as_default: bool = False
    # When True, the executor must not auto-trigger an interactive thinking selector.
    # This is required for in-prompt model switching where the terminal is already
    # controlled by a prompt_toolkit PromptSession.
    defer_thinking_selection: bool = False
    # When False, do not emit WelcomeEvent (which renders a banner/panel).
    # This is useful for in-prompt model switching where extra output is noisy.
    emit_welcome_event: bool = True

    # When False, do not emit the "Switched to: …" developer message.
    # This is useful for in-prompt model switching where extra output is noisy.
    emit_switch_message: bool = True

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_change_model(self)


class ChangeCompactModelOperation(Operation):
    """Operation for changing the compact model (used for session compaction)."""

    type: OperationType = OperationType.CHANGE_COMPACT_MODEL
    session_id: str
    model_name: str | None
    save_as_default: bool = False

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_change_compact_model(self)


class ChangeThinkingOperation(Operation):
    """Operation for changing the thinking/reasoning configuration."""

    type: OperationType = OperationType.CHANGE_THINKING
    session_id: str
    thinking: Thinking | None = None
    emit_welcome_event: bool = True
    emit_switch_message: bool = True

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_change_thinking(self)


class ChangeSubAgentModelOperation(Operation):
    """Operation for changing the model used by a specific sub-agent."""

    type: OperationType = OperationType.CHANGE_SUB_AGENT_MODEL
    session_id: str
    sub_agent_type: str
    # When None, clear explicit override and fall back to the sub-agent's default
    # behavior (usually inherit from main agent; some sub-agents auto-resolve a
    # suitable model, e.g. ImageGen).
    model_name: str | None
    save_as_default: bool = False

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_change_sub_agent_model(self)


class ClearSessionOperation(Operation):
    """Operation for clearing the active session and starting a new one."""

    type: OperationType = OperationType.CLEAR_SESSION
    session_id: str

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_clear_session(self)


class ResumeSessionOperation(Operation):
    """Operation for resuming a different session."""

    type: OperationType = OperationType.RESUME_SESSION
    target_session_id: str

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_resume_session(self)


class ExportSessionOperation(Operation):
    """Operation for exporting a session transcript to HTML."""

    type: OperationType = OperationType.EXPORT_SESSION
    session_id: str
    output_path: str | None = None

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_export_session(self)


class InterruptOperation(Operation):
    """Operation for interrupting currently running tasks."""

    type: OperationType = OperationType.INTERRUPT
    target_session_id: str | None = None  # If None, interrupt all sessions

    async def execute(self, handler: OperationHandler) -> None:
        """Execute interrupt by cancelling active tasks."""
        await handler.handle_interrupt(self)


class InitAgentOperation(Operation):
    """Operation for initializing an agent and replaying history if any.

    If session_id is None, a new session is created with an auto-generated ID.
    If session_id is provided, attempts to load existing session or creates new one.
    """

    type: OperationType = OperationType.INIT_AGENT
    session_id: str | None = None

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_init_agent(self)


class EndOperation(Operation):
    """Operation for gracefully stopping the executor."""

    type: OperationType = OperationType.END

    async def execute(self, handler: OperationHandler) -> None:
        """Execute end operation - this is a no-op, just signals the executor to stop."""
        pass


class Submission(BaseModel):
    """A submission represents a request sent to the executor for processing."""

    id: str
    operation: Operation
