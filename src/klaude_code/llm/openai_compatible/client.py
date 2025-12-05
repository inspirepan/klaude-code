import json
from collections.abc import AsyncGenerator
from typing import override

import httpx
import openai
from openai.types.chat.completion_create_params import CompletionCreateParamsStreaming

from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.openai_compatible.input import convert_history_to_input, convert_tool_schema
from klaude_code.llm.openai_compatible.stream_processor import StreamStateManager
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, convert_usage
from klaude_code.protocol import llm_param, model
from klaude_code.trace import DebugType, log_debug


def build_payload(param: llm_param.LLMCallParameter) -> tuple[CompletionCreateParamsStreaming, dict[str, object]]:
    """Build OpenAI API request parameters."""
    messages = convert_history_to_input(param.input, param.system, param.model)
    tools = convert_tool_schema(param.tools)

    extra_body: dict[str, object] = {}

    if param.thinking:
        extra_body["thinking"] = {
            "type": param.thinking.type,
            "budget": param.thinking.budget_tokens,
        }

    payload: CompletionCreateParamsStreaming = {
        "model": str(param.model),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "stream": True,
        "messages": messages,
        "temperature": param.temperature,
        "max_tokens": param.max_tokens,
        "tools": tools,
        "reasoning_effort": param.thinking.reasoning_effort if param.thinking else None,
        "verbosity": param.verbosity,
    }

    return payload, extra_body


@register(llm_param.LLMClientProtocol.OPENAI)
class OpenAICompatibleClient(LLMClientABC):
    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        if config.is_azure:
            if not config.base_url:
                raise ValueError("Azure endpoint is required")
            client = openai.AsyncAzureOpenAI(
                api_key=config.api_key,
                azure_endpoint=str(config.base_url),
                api_version=config.azure_api_version,
                timeout=httpx.Timeout(300.0, connect=15.0, read=285.0),
            )
        else:
            client = openai.AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=httpx.Timeout(300.0, connect=15.0, read=285.0),
            )
        self.client: openai.AsyncAzureOpenAI | openai.AsyncOpenAI = client

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> AsyncGenerator[model.ConversationItem]:
        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        payload, extra_body = build_payload(param)
        extra_headers: dict[str, str] = {"extra": json.dumps({"session_id": param.session_id}, sort_keys=True)}

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

        state = StreamStateManager(param_model=str(param.model))

        try:
            async for event in await stream:
                log_debug(
                    event.model_dump_json(exclude_none=True),
                    style="blue",
                    debug_type=DebugType.LLM_STREAM,
                )
                if not state.response_id and event.id:
                    state.set_response_id(event.id)
                    yield model.StartItem(response_id=event.id)
                if event.usage is not None:
                    metadata_tracker.set_usage(convert_usage(event.usage, param.context_limit, param.max_tokens))
                if event.model:
                    metadata_tracker.set_model_name(event.model)
                if provider := getattr(event, "provider", None):
                    metadata_tracker.set_provider(str(provider))

                if len(event.choices) == 0:
                    continue

                # Support Moonshot Kimi K2's usage field in choice
                if usage := getattr(event.choices[0], "usage", None):
                    metadata_tracker.set_usage(
                        convert_usage(
                            openai.types.CompletionUsage.model_validate(usage),
                            param.context_limit,
                            param.max_tokens,
                        )
                    )

                delta = event.choices[0].delta

                # Reasoning
                if (
                    reasoning_content := getattr(delta, "reasoning_content", None)
                    or getattr(delta, "reasoning", None)
                    or ""
                ):
                    metadata_tracker.record_token()
                    state.stage = "reasoning"
                    state.accumulated_reasoning.append(reasoning_content)
                    yield model.ReasoningTextDelta(
                        content=reasoning_content,
                        response_id=state.response_id,
                    )

                # Assistant
                if delta.content and (
                    state.stage == "assistant" or delta.content.strip()
                ):  # Process all content in assistant stage, filter empty content in reasoning stage
                    metadata_tracker.record_token()
                    if state.stage == "reasoning":
                        for item in state.flush_reasoning():
                            yield item
                    elif state.stage == "tool":
                        for item in state.flush_tool_calls():
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
