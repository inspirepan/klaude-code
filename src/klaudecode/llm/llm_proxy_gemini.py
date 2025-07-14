import uuid
from typing import Dict, List, Optional

from openai.types.chat import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall
from openai.types.chat.chat_completion_message_tool_call import Function

from ..message import ToolCall, count_tokens
from .llm_proxy_openai import OpenAIProxy


class GeminiProxy(OpenAIProxy):
    def _create_tool_call_accumulator(self):
        """Create Gemini-specific tool call accumulator."""
        return self.GeminiToolCallChunkAccumulator()

    class GeminiToolCallChunkAccumulator:
        def __init__(self) -> None:
            self.tool_call_dict: Dict[int, ChatCompletionMessageToolCall] = {}

        def add_chunks(self, chunks: Optional[List[ChoiceDeltaToolCall]]) -> None:
            if not chunks:
                return
            for chunk in chunks:
                self.add_chunk(chunk)

        def add_chunk(self, chunk: ChoiceDeltaToolCall) -> None:
            if not chunk:
                return

            index = chunk.index
            if index not in self.tool_call_dict:
                # Generate unique ID for this tool call
                tool_call_id = f'call_{uuid.uuid4().hex[:8]}_{index}'
                self.tool_call_dict[index] = ChatCompletionMessageToolCall(
                    id=tool_call_id,
                    function=Function(arguments='', name=''),
                    type='function',
                )

            if chunk.function and chunk.function.name:
                self.tool_call_dict[index].function.name = chunk.function.name
            if chunk.function and chunk.function.arguments:
                self.tool_call_dict[index].function.arguments += chunk.function.arguments

        def get_tool_call_msg_dict(self) -> Dict[str, ToolCall]:
            return {
                raw_tc.id: ToolCall(
                    id=raw_tc.id,
                    tool_name=raw_tc.function.name,
                    tool_args=raw_tc.function.arguments,
                )
                for raw_tc in self.tool_call_dict.values()
            }

        def count_tokens(self) -> int:
            tokens = 0
            for tc in self.tool_call_dict.values():
                tokens += count_tokens(tc.function.name) + count_tokens(tc.function.arguments)
            return tokens
