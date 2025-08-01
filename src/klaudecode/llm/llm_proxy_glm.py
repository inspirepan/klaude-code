import uuid
from typing import List, Optional

from openai.types.chat import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall
from openai.types.chat.chat_completion_message_tool_call import Function

from .llm_proxy_openai import OpenAIProxy


class GLMProxy(OpenAIProxy):
    def _create_tool_call_accumulator(self):
        """Create GLM-specific tool call accumulator."""
        return self.GLMToolCallChunkAccumulator()

    class GLMToolCallChunkAccumulator(OpenAIProxy.OpenAIToolCallChunkAccumulator):
        def __init__(self) -> None:
            super().__init__()
            self._call_counter = 0  # Counter for generating IDs

        def add_chunks(self, chunks: Optional[List[ChoiceDeltaToolCall]]) -> None:
            if not chunks:
                return

            # GLM sends multiple complete tool calls in one chunk
            # Only the first one has an ID, others need ID generation
            for i, chunk in enumerate(chunks):
                if i == 0 and chunk.id:
                    # First chunk with valid ID
                    self._add_tool_call(chunk, chunk.id)
                else:
                    # Subsequent chunks without ID, generate one
                    generated_id = f"call_{uuid.uuid4().hex[:8]}_{self._call_counter}"
                    self._call_counter += 1
                    self._add_tool_call(chunk, generated_id)

        def _add_tool_call(self, chunk: ChoiceDeltaToolCall, tool_id: str) -> None:
            """Add a complete tool call with GLM's format (complete JSON arguments)."""
            if not chunk or not chunk.function:
                return
            self.tool_call_list.append(
                ChatCompletionMessageToolCall(
                    id=tool_id,
                    function=Function(arguments="", name=""),
                    type="function",
                )
            )

            if chunk.function.name:
                self.tool_call_list[-1].function.name = chunk.function.name
            if chunk.function.arguments:
                # GLM sends complete arguments, not incremental
                # Override the append behavior by setting directly
                self.tool_call_list[-1].function.arguments = chunk.function.arguments
