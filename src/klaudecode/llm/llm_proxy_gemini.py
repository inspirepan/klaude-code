import uuid
from typing import Dict

from openai.types.chat import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall
from openai.types.chat.chat_completion_message_tool_call import Function

from .llm_proxy_openai import OpenAIProxy


class GeminiProxy(OpenAIProxy):
    def _create_tool_call_accumulator(self):
        """Create Gemini-specific tool call accumulator."""
        return self.GeminiToolCallChunkAccumulator()

    class GeminiToolCallChunkAccumulator(OpenAIProxy.OpenAIToolCallChunkAccumulator):
        def __init__(self) -> None:
            super().__init__()
            self.tool_call_dict: Dict[int, ChatCompletionMessageToolCall] = {}

        def add_chunk(self, chunk: ChoiceDeltaToolCall) -> None:
            if not chunk:
                return

            # Gemini uses index to identify different tool calls in streaming response
            index = chunk.index
            if index not in self.tool_call_dict:
                # Generate unique ID for this tool call
                tool_call_id = f'call_{uuid.uuid4().hex[:8]}_{index}'
                self.tool_call_dict[index] = ChatCompletionMessageToolCall(
                    id=tool_call_id,
                    function=Function(arguments='', name=''),
                    type='function',
                )
                # Also add to parent's list for compatibility
                self.tool_call_list.append(self.tool_call_dict[index])

            # Update the tool call at this index
            if chunk.function and chunk.function.name:
                self.tool_call_dict[index].function.name = chunk.function.name
            if chunk.function and chunk.function.arguments:
                self.tool_call_dict[index].function.arguments += chunk.function.arguments
