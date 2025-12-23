import re
from abc import ABC, abstractmethod

from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall
from pydantic import BaseModel, Field

from klaude_code.protocol import model
from klaude_code.trace.log import log_debug


def normalize_tool_name(name: str) -> str:
    """Normalize tool name from Gemini-3 format.

    Gemini-3 sometimes returns tool names in format like 'tool_Edit_mUoY2p3W3r3z8uO5P2nZ'.
    This function extracts the actual tool name (e.g., 'Edit').
    """
    match = re.match(r"^tool_([A-Za-z]+)_[A-Za-z0-9]+$", name)
    if match:
        normalized = match.group(1)
        log_debug(f"Gemini-3 tool name normalized: {name} -> {normalized}", style="yellow")
        return normalized
    return name


class ToolCallAccumulatorABC(ABC):
    @abstractmethod
    def add(self, chunks: list[ChoiceDeltaToolCall]) -> None:
        pass

    @abstractmethod
    def get(self) -> list[model.ToolCallItem]:
        pass


class BasicToolCallAccumulator(ToolCallAccumulatorABC, BaseModel):
    """
    Support for API:
    - returns multiple tool calls within a single response in a serial manner.
    - Each step contains exactly one chunk.

    e.g.:
    Claude, GPT series
    The sequence for each tool call follows this pattern:
    - Initial chunk: contains tool call id and function name
    - Subsequent chunks: contain argument fragments with id and name set to None
    - Every chunk has a valid index
    - Pattern repeats for the next tool call
    [ChoiceDeltaToolCall(index=0, id='toolu_vrtx_01QxTq6QeJZd9tTLt6pvtSy6', function=ChoiceDeltaToolCallFunction(arguments='', name='Bash'), type='function')]
    [ChoiceDeltaToolCall(index=0, id=None, function=ChoiceDeltaToolCallFunction(arguments='', name=None), type='function')]
    [ChoiceDeltaToolCall(index=0, id=None, function=ChoiceDeltaToolCallFunction(arguments='{"comm', name=None), type='function')]
    [ChoiceDeltaToolCall(index=0, id=None, function=ChoiceDeltaToolCallFunction(arguments='an', name=None), type='function')]
    [ChoiceDeltaToolCall(index=0, id=None, function=ChoiceDeltaToolCallFunction(arguments='d": "', name=None), type='function')]
    [ChoiceDeltaToolCall(index=0, id=None, function=ChoiceDeltaToolCallFunction(arguments='pwd"}', name=None), type='function')]
    [ChoiceDeltaToolCall(index=1, id='toolu_vrtx_01Uvxge2edYAZBnNLoYGeDBg', function=ChoiceDeltaToolCallFunction(arguments='', name='Bash'), type='function')]
    [ChoiceDeltaToolCall(index=1, id=None, function=ChoiceDeltaToolCallFunction(arguments='', name=None), type='function')]
    [ChoiceDeltaToolCall(index=1, id=None, function=ChoiceDeltaToolCallFunction(arguments='{"com', name=None), type='function')]
    [ChoiceDeltaToolCall(index=1, id=None, function=ChoiceDeltaToolCallFunction(arguments='mand":', name=None), type='function')]
    [ChoiceDeltaToolCall(index=1, id=None, function=ChoiceDeltaToolCallFunction(arguments=' "ls"}', name=None), type='function')]

    Grok, Gemini
    Each step is one completed tool call
    [ChoiceDeltaToolCall(index=0, id='call_83297568', function=ChoiceDeltaToolCallFunction(arguments='{"command":"pwd"}', name='Bash'), type='function')]
    [ChoiceDeltaToolCall(index=1, id='call_88931225', function=ChoiceDeltaToolCallFunction(arguments='{"command":"ls"}', name='Bash'), type='function')]
    """

    chunks_by_step: list[list[ChoiceDeltaToolCall]] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    response_id: str | None = None

    def add(self, chunks: list[ChoiceDeltaToolCall]) -> None:
        self.chunks_by_step.append(chunks)

    def get(self) -> list[model.ToolCallItem]:
        result: list[model.ToolCallItem] = []
        current_index = -1
        for current_step in self.chunks_by_step:
            if len(current_step) == 0:
                continue
            first_chunk = current_step[0]
            if first_chunk.index != current_index:
                current_index = first_chunk.index
                result.append(
                    model.ToolCallItem(
                        id=first_chunk.id,
                        name="",
                        arguments="",
                        call_id=first_chunk.id or "",
                        response_id=self.response_id,
                    )
                )
            if first_chunk.function is None:
                continue
            if first_chunk.function.name:
                result[-1].name = normalize_tool_name(first_chunk.function.name)
            if first_chunk.function.arguments:
                result[-1].arguments += first_chunk.function.arguments
        return result
