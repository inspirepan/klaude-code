"""
Operation handler protocol for the executor system.

This module defines the protocol that operation handlers must implement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from klaude_code.protocol.op import (
        ChangeModelOperation,
        ChangeThinkingOperation,
        ClearSessionOperation,
        ExportSessionOperation,
        InitAgentOperation,
        InterruptOperation,
        ResumeSessionOperation,
        RunAgentOperation,
        UserInputOperation,
    )


class OperationHandler(Protocol):
    """Protocol defining the interface for handling operations."""

    async def handle_user_input(self, operation: UserInputOperation) -> None:
        """Handle a user input operation."""
        ...

    async def handle_run_agent(self, operation: RunAgentOperation) -> None:
        """Handle a run agent operation."""
        ...

    async def handle_change_model(self, operation: ChangeModelOperation) -> None:
        """Handle a change model operation."""
        ...

    async def handle_change_thinking(self, operation: ChangeThinkingOperation) -> None:
        """Handle a change thinking operation."""
        ...

    async def handle_clear_session(self, operation: ClearSessionOperation) -> None:
        """Handle a clear session operation."""
        ...

    async def handle_resume_session(self, operation: ResumeSessionOperation) -> None:
        """Handle a resume session operation."""
        ...

    async def handle_export_session(self, operation: ExportSessionOperation) -> None:
        """Handle an export session operation."""
        ...

    async def handle_interrupt(self, operation: InterruptOperation) -> None:
        """Handle an interrupt operation."""
        ...

    async def handle_init_agent(self, operation: InitAgentOperation) -> None:
        """Handle an init agent operation."""
        ...
