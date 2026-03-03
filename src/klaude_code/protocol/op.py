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
from klaude_code.protocol.user_interaction import UserInteractionResponse

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
    EXPORT_SESSION = "export_session"
    INTERRUPT = "interrupt"
    CLOSE_SESSION = "close_session"
    USER_INTERACTION_RESPOND = "user_interaction_respond"
    INIT_AGENT = "init_agent"


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
    # behavior.
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
    session_id: str

    async def execute(self, handler: OperationHandler) -> None:
        """Execute interrupt by cancelling active tasks."""
        await handler.handle_interrupt(self)


class CloseSessionOperation(Operation):
    """Operation for closing a session runtime explicitly."""

    type: OperationType = OperationType.CLOSE_SESSION
    session_id: str
    force: bool = False

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_close_session(self)


class UserInteractionRespondOperation(Operation):
    """Operation for sending user interaction response back to core."""

    type: OperationType = OperationType.USER_INTERACTION_RESPOND
    session_id: str
    request_id: str
    response: UserInteractionResponse

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_user_interaction_respond(self)


class InitAgentOperation(Operation):
    """Operation for initializing an agent and replaying history if any.

    The caller must always provide session_id.
    If the target session does not exist yet, a new session will be initialized.
    """

    type: OperationType = OperationType.INIT_AGENT
    session_id: str

    async def execute(self, handler: OperationHandler) -> None:
        await handler.handle_init_agent(self)


