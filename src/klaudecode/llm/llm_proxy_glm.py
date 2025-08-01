import uuid
from typing import List, Optional

from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

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
                    self._add_complete_tool_call(chunk, chunk.id)
                else:
                    # Subsequent chunks without ID, generate one
                    generated_id = f"call_{uuid.uuid4().hex[:8]}_{self._call_counter}"
                    self._call_counter += 1
                    self._add_complete_tool_call(chunk, generated_id)

        def add_chunk(self, chunk: ChoiceDeltaToolCall) -> None:
            """Handle single chunk - GLM typically sends multiple chunks together."""
            if not chunk:
                return

            # For single chunk, check if it has ID
            if chunk.id:
                self._add_complete_tool_call(chunk, chunk.id)
            else:
                # Generate ID for chunks without ID
                generated_id = f"call_{uuid.uuid4().hex[:8]}_{self._call_counter}"
                self._call_counter += 1
                self._add_complete_tool_call(chunk, generated_id)

        def _add_complete_tool_call(
            self, chunk: ChoiceDeltaToolCall, tool_id: str
        ) -> None:
            """Add a complete tool call with GLM's format (complete JSON arguments)."""
            if not chunk or not chunk.function:
                return

            # Use parent's method to add new tool call
            self._add_new_tool_call(tool_id)

            # GLM sends complete tool calls with full JSON arguments
            if chunk.function.name:
                self._update_tool_name(chunk.function.name)
            if chunk.function.arguments:
                # GLM sends complete arguments, not incremental
                # Override the append behavior by setting directly
                self.tool_call_list[-1].function.arguments = chunk.function.arguments
