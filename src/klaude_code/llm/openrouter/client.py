import json
from collections.abc import AsyncGenerator
from typing import override

import httpx
import openai
from openai.types.chat.completion_create_params import CompletionCreateParamsStreaming

from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.openai_compatible.input import convert_tool_schema
from klaude_code.llm.openai_compatible.stream_processor import StreamStateManager
from klaude_code.llm.openrouter.input import convert_history_to_input, is_claude_model
from klaude_code.llm.openrouter.reasoning_handler import ReasoningDetail, ReasoningStreamHandler
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, convert_usage
from klaude_code.protocol import llm_param, model
from klaude_code.trace import DebugType, is_debug_enabled, log, log_debug


def build_payload(
    param: llm_param.LLMCallParameter,
) -> tuple[CompletionCreateParamsStreaming, dict[str, object], dict[str, str]]:
    """Build OpenRouter API request parameters."""
    messages = convert_history_to_input(param.input, param.system, param.model)
    tools = convert_tool_schema(param.tools)

    extra_body: dict[str, object] = {
        "usage": {"include": True},  # To get the cache tokens at the end of the response
    }
    if is_debug_enabled():
        extra_body["debug"] = {
            "echo_upstream_body": True
        }  # https://openrouter.ai/docs/api/reference/errors-and-debugging#debug-option-shape
    extra_headers: dict[str, str] = {}

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
        extra_headers["x-anthropic-beta"] = "fine-grained-tool-streaming-2025-05-14,interleaved-thinking-2025-05-14"

    payload: CompletionCreateParamsStreaming = {
        "model": str(param.model),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "stream": True,
        "messages": messages,
        "temperature": param.temperature,
        "max_tokens": param.max_tokens,
        "tools": tools,
        "verbosity": param.verbosity,
    }

    return payload, extra_body, extra_headers


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
    async def call(self, param: llm_param.LLMCallParameter) -> AsyncGenerator[model.ConversationItem]:
        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        payload, extra_body, extra_headers = build_payload(param)

        log_debug(
            json.dumps({**payload, **extra_body}, ensure_ascii=False, default=str),
            style="yellow",
            debug_type=DebugType.LLM_PAYLOAD,
        )

        stream = self.client.chat.completions.create(
            **payload,
            extra_body=extra_body,
            extra_headers=extra_headers,
        )

        reasoning_handler = ReasoningStreamHandler(
            param_model=str(param.model),
            response_id=None,
        )

        state = StreamStateManager(
            param_model=str(param.model),
            reasoning_flusher=reasoning_handler.flush,
        )

        try:
            async for event in await stream:
                log_debug(
                    event.model_dump_json(exclude_none=True),
                    style="blue",
                    debug_type=DebugType.LLM_STREAM,
                )

                if not state.response_id and event.id:
                    state.set_response_id(event.id)
                    reasoning_handler.set_response_id(event.id)
                    yield model.StartItem(response_id=event.id)
                if event.usage is not None:
                    metadata_tracker.set_usage(convert_usage(event.usage, param.context_limit, param.max_tokens))
                if event.model:
                    metadata_tracker.set_model_name(event.model)
                if provider := getattr(event, "provider", None):
                    metadata_tracker.set_provider(str(provider))
                if len(event.choices) == 0:
                    continue
                delta = event.choices[0].delta

                # Reasoning
                if reasoning_details := getattr(delta, "reasoning_details", None):
                    for item in reasoning_details:
                        try:
                            reasoning_detail = ReasoningDetail.model_validate(item)
                            metadata_tracker.record_token()
                            state.stage = "reasoning"
                            # Yield delta immediately for streaming
                            if reasoning_detail.text:
                                yield model.ReasoningTextDelta(
                                    content=reasoning_detail.text,
                                    response_id=state.response_id,
                                )
                            if reasoning_detail.summary:
                                yield model.ReasoningTextDelta(
                                    content=reasoning_detail.summary,
                                    response_id=state.response_id,
                                )
                            # Keep existing handler logic for final items
                            for conversation_item in reasoning_handler.on_detail(reasoning_detail):
                                yield conversation_item
                        except Exception as e:
                            log("reasoning_details error", str(e), style="red")

                # Assistant
                if delta.content and (
                    state.stage == "assistant" or delta.content.strip()
                ):  # Process all content in assistant stage, filter empty content in reasoning stage
                    metadata_tracker.record_token()
                    if state.stage == "reasoning":
                        for item in state.flush_reasoning():
                            yield item
                    state.stage = "assistant"
                    state.accumulated_content.append(delta.content)
                    yield model.AssistantMessageDelta(
                        content=delta.content,
                        response_id=state.response_id,
                    )

                # Tool
                if delta.tool_calls and len(delta.tool_calls) > 0:
                    metadata_tracker.record_token()
                    if state.stage == "reasoning":
                        for item in state.flush_reasoning():
                            yield item
                    elif state.stage == "assistant":
                        for item in state.flush_assistant():
                            yield item
                    state.stage = "tool"
                    # Emit ToolCallStartItem for new tool calls
                    for tc in delta.tool_calls:
                        if tc.index not in state.emitted_tool_start_indices and tc.function and tc.function.name:
                            state.emitted_tool_start_indices.add(tc.index)
                            yield model.ToolCallStartItem(
                                response_id=state.response_id,
                                call_id=tc.id or "",
                                name=tc.function.name,
                            )
                    state.accumulated_tool_calls.add(delta.tool_calls)

        except (openai.OpenAIError, httpx.HTTPError) as e:
            yield model.StreamErrorItem(error=f"{e.__class__.__name__} {e!s}")

        # Finalize
        for item in state.flush_all():
            yield item

        metadata_tracker.set_response_id(state.response_id)
        yield metadata_tracker.finalize()
