from collections.abc import AsyncGenerator
from typing import Literal, override

import httpx
import openai

from klaude_code.llm.client import LLMClientABC, call_with_logged_payload
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.openai_compatible.input import convert_tool_schema
from klaude_code.llm.openai_compatible.tool_call_accumulator import BasicToolCallAccumulator, ToolCallAccumulatorABC
from klaude_code.llm.openrouter.input import convert_history_to_input, is_claude_model
from klaude_code.llm.openrouter.reasoning_handler import ReasoningDetail, ReasoningStreamHandler
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, convert_usage
from klaude_code.protocol import llm_param, model
from klaude_code.trace import DebugType, log, log_debug


@register(llm_param.LLMClientProtocol.OPENROUTER)
class OpenRouterClient(LLMClientABC):
    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        client = openai.AsyncOpenAI(
            api_key=config.api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=httpx.Timeout(300.0, connect=15.0, read=285.0),
        )
        self.client: openai.AsyncOpenAI = client

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> AsyncGenerator[model.ConversationItem, None]:
        param = apply_config_defaults(param, self.get_llm_config())
        messages = convert_history_to_input(param.input, param.system, param.model)
        tools = convert_tool_schema(param.tools)

        metadata_tracker = MetadataTracker()

        extra_body: dict[str, object] = {
            "usage": {"include": True}  # To get the cache tokens at the end of the response
        }
        extra_headers = {}

        if param.thinking:
            if param.thinking.budget_tokens is not None:
                extra_body["reasoning"] = {
                    "max_tokens": param.thinking.budget_tokens,
                    "enable": True,
                }  # OpenRouter: https://openrouter.ai/docs/use-cases/reasoning-tokens#anthropic-models-with-reasoning-tokens
            elif param.thinking.reasoning_effort is not None:
                extra_body["reasoning"] = {
                    "effort": param.thinking.reasoning_effort,
                }
        if param.provider_routing:
            extra_body["provider"] = param.provider_routing.model_dump(exclude_none=True)
        if is_claude_model(param.model):
            extra_headers["anthropic-beta"] = (
                "interleaved-thinking-2025-05-14"  # Not working yet, maybe OpenRouter's issue, or Anthropic: Interleaved thinking is only supported for tools used via the Messages API.
            )

        stream = call_with_logged_payload(
            self.client.chat.completions.create,
            model=str(param.model),
            tool_choice="auto",
            parallel_tool_calls=True,
            stream=True,
            messages=messages,
            temperature=param.temperature,
            max_tokens=param.max_tokens,
            tools=tools,
            verbosity=param.verbosity,
            extra_body=extra_body,  # pyright: ignore[reportUnknownArgumentType]
            extra_headers=extra_headers,  # pyright: ignore[reportUnknownArgumentType]
        )

        stage: Literal["waiting", "reasoning", "assistant", "tool", "done"] = "waiting"
        response_id: str | None = None
        accumulated_content: list[str] = []
        accumulated_tool_calls: ToolCallAccumulatorABC = BasicToolCallAccumulator()
        emitted_tool_start_indices: set[int] = set()
        reasoning_handler = ReasoningStreamHandler(
            param_model=str(param.model),
            response_id=response_id,
        )

        def flush_reasoning_items() -> list[model.ConversationItem]:
            return reasoning_handler.flush()

        def flush_assistant_items() -> list[model.ConversationItem]:
            nonlocal accumulated_content
            if len(accumulated_content) == 0:
                return []
            item = model.AssistantMessageItem(
                content="".join(accumulated_content),
                response_id=response_id,
            )
            accumulated_content = []
            return [item]

        def flush_tool_call_items() -> list[model.ToolCallItem]:
            nonlocal accumulated_tool_calls
            items: list[model.ToolCallItem] = accumulated_tool_calls.get()
            if items:
                accumulated_tool_calls.chunks_by_step = []  # pyright: ignore[reportAttributeAccessIssue]
            return items

        try:
            async for event in await stream:
                log_debug(
                    event.model_dump_json(exclude_none=True),
                    style="blue",
                    debug_type=DebugType.LLM_STREAM,
                )
                if not response_id and event.id:
                    response_id = event.id
                    reasoning_handler.set_response_id(response_id)
                    accumulated_tool_calls.response_id = response_id
                    yield model.StartItem(response_id=response_id)
                if (
                    event.usage is not None and event.usage.completion_tokens is not None  # pyright: ignore[reportUnnecessaryComparison]
                ):  # gcp gemini will return None usage field
                    metadata_tracker.set_usage(convert_usage(event.usage, param.context_limit))
                if event.model:
                    metadata_tracker.set_model_name(event.model)
                if provider := getattr(event, "provider", None):
                    metadata_tracker.set_provider(str(provider))

                if len(event.choices) == 0:
                    continue
                delta = event.choices[0].delta

                # Reasoning
                if hasattr(delta, "reasoning_details") and getattr(delta, "reasoning_details"):
                    reasoning_details = getattr(delta, "reasoning_details")
                    for item in reasoning_details:
                        try:
                            reasoning_detail = ReasoningDetail.model_validate(item)
                            metadata_tracker.record_token()
                            stage = "reasoning"
                            for conversation_item in reasoning_handler.on_detail(reasoning_detail):
                                yield conversation_item
                        except Exception as e:
                            log("reasoning_details error", str(e), style="red")

                # Assistant
                if delta.content and (
                    stage == "assistant" or delta.content.strip()
                ):  # Process all content in assistant stage, filter empty content in reasoning stage
                    metadata_tracker.record_token()
                    if stage == "reasoning":
                        for item in flush_reasoning_items():
                            yield item
                    stage = "assistant"
                    accumulated_content.append(delta.content)
                    yield model.AssistantMessageDelta(
                        content=delta.content,
                        response_id=response_id,
                    )

                # Tool
                if delta.tool_calls and len(delta.tool_calls) > 0:
                    metadata_tracker.record_token()
                    if stage == "reasoning":
                        for item in flush_reasoning_items():
                            yield item
                    elif stage == "assistant":
                        for item in flush_assistant_items():
                            yield item
                    stage = "tool"
                    # Emit ToolCallStartItem for new tool calls
                    for tc in delta.tool_calls:
                        if tc.index not in emitted_tool_start_indices and tc.function and tc.function.name:
                            emitted_tool_start_indices.add(tc.index)
                            yield model.ToolCallStartItem(
                                response_id=response_id,
                                call_id=tc.id or "",
                                name=tc.function.name,
                            )
                    accumulated_tool_calls.add(delta.tool_calls)

        except (openai.OpenAIError, httpx.HTTPError) as e:
            yield model.StreamErrorItem(error=f"{e.__class__.__name__} {str(e)}")

        # Finalize
        for item in flush_reasoning_items():
            yield item

        for item in flush_assistant_items():
            yield item

        if stage == "tool":
            for tool_call_item in flush_tool_call_items():
                yield tool_call_item

        metadata_tracker.set_response_id(response_id)
        yield metadata_tracker.finalize()
