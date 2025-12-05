"""Shared stream processing utilities for OpenAI-compatible clients.

This module provides a reusable stream state manager that handles the common
logic for accumulating and flushing reasoning, assistant content, and tool calls
across different LLM providers (OpenAI-compatible, OpenRouter).
"""

from collections.abc import Callable
from typing import Literal

from klaude_code.llm.openai_compatible.tool_call_accumulator import BasicToolCallAccumulator, ToolCallAccumulatorABC
from klaude_code.protocol import model

StreamStage = Literal["waiting", "reasoning", "assistant", "tool"]


class StreamStateManager:
    """Manages streaming state and provides flush operations for accumulated content.

    This class encapsulates the common state management logic used by both
    OpenAI-compatible and OpenRouter clients, reducing code duplication.
    """

    def __init__(
        self,
        param_model: str,
        response_id: str | None = None,
        reasoning_flusher: Callable[[], list[model.ConversationItem]] | None = None,
    ):
        self.param_model = param_model
        self.response_id = response_id
        self.stage: StreamStage = "waiting"
        self.accumulated_reasoning: list[str] = []
        self.accumulated_content: list[str] = []
        self.accumulated_tool_calls: ToolCallAccumulatorABC = BasicToolCallAccumulator()
        self.emitted_tool_start_indices: set[int] = set()
        self._reasoning_flusher = reasoning_flusher

    def set_response_id(self, response_id: str) -> None:
        """Set the response ID once received from the stream."""
        self.response_id = response_id
        self.accumulated_tool_calls.response_id = response_id  # pyright: ignore[reportAttributeAccessIssue]

    def flush_reasoning(self) -> list[model.ConversationItem]:
        """Flush accumulated reasoning content and return items."""
        if self._reasoning_flusher is not None:
            return self._reasoning_flusher()
        if not self.accumulated_reasoning:
            return []
        item = model.ReasoningTextItem(
            content="".join(self.accumulated_reasoning),
            response_id=self.response_id,
            model=self.param_model,
        )
        self.accumulated_reasoning = []
        return [item]

    def flush_assistant(self) -> list[model.ConversationItem]:
        """Flush accumulated assistant content and return items."""
        if not self.accumulated_content:
            return []
        item = model.AssistantMessageItem(
            content="".join(self.accumulated_content),
            response_id=self.response_id,
        )
        self.accumulated_content = []
        return [item]

    def flush_tool_calls(self) -> list[model.ToolCallItem]:
        """Flush accumulated tool calls and return items."""
        items: list[model.ToolCallItem] = self.accumulated_tool_calls.get()
        if items:
            self.accumulated_tool_calls.chunks_by_step = []  # pyright: ignore[reportAttributeAccessIssue]
        return items

    def flush_all(self) -> list[model.ConversationItem]:
        """Flush all accumulated content in order: reasoning, assistant, tool calls."""
        items: list[model.ConversationItem] = []
        items.extend(self.flush_reasoning())
        items.extend(self.flush_assistant())
        if self.stage == "tool":
            items.extend(self.flush_tool_calls())
        return items
