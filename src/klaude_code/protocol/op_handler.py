"""
Operation handler protocol for the executor system.

This module defines the protocol that operation handlers must implement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from klaude_code.protocol.op import InitAgentOperation, InterruptOperation, UserInputOperation


class OperationHandler(Protocol):
    """Protocol defining the interface for handling operations."""

    async def handle_user_input(self, operation: UserInputOperation) -> None:
        """Handle a user input operation."""
        ...

    async def handle_interrupt(self, operation: InterruptOperation) -> None:
        """Handle an interrupt operation."""
        ...

    async def handle_init_agent(self, operation: InitAgentOperation) -> None:
        """Handle an init agent operation."""
        ...
