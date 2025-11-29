import json
import time
from collections.abc import AsyncGenerator
from typing import override

import anthropic
import httpx
from anthropic import RateLimitError
from anthropic.types.beta.beta_input_json_delta import BetaInputJSONDelta
from anthropic.types.beta.beta_raw_content_block_delta_event import BetaRawContentBlockDeltaEvent
from anthropic.types.beta.beta_raw_content_block_start_event import BetaRawContentBlockStartEvent
from anthropic.types.beta.beta_raw_content_block_stop_event import BetaRawContentBlockStopEvent
from anthropic.types.beta.beta_raw_message_delta_event import BetaRawMessageDeltaEvent
from anthropic.types.beta.beta_raw_message_start_event import BetaRawMessageStartEvent
from anthropic.types.beta.beta_signature_delta import BetaSignatureDelta
from anthropic.types.beta.beta_text_delta import BetaTextDelta
from anthropic.types.beta.beta_thinking_delta import BetaThinkingDelta
from anthropic.types.beta.beta_tool_use_block import BetaToolUseBlock

from klaude_code import const
from klaude_code.llm.anthropic.input import convert_history_to_input, convert_system_to_input, convert_tool_schema
from klaude_code.llm.client import LLMClientABC, call_with_logged_payload
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.registry import register
from klaude_code.protocol import model
from klaude_code.protocol.llm_parameter import (
    LLMCallParameter,
    LLMClientProtocol,
    LLMConfigParameter,
)
from klaude_code.protocol.model import StreamErrorItem
from klaude_code.trace import DebugType, log_debug


@register(LLMClientProtocol.ANTHROPIC)
class AnthropicClient(LLMClientABC):
    def __init__(self, config: LLMConfigParameter):
        super().__init__(config)
        client = anthropic.AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=httpx.Timeout(300.0, connect=15.0, read=285.0),
        )
        self.client: anthropic.AsyncAnthropic = client

    @classmethod
    @override
    def create(cls, config: LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: LLMCallParameter) -> AsyncGenerator[model.ConversationItem, None]:
        param = apply_config_defaults(param, self.get_llm_config())

        request_start_time = time.time()
        first_token_time: float | None = None
        last_token_time: float | None = None

        messages = convert_history_to_input(param.input, param.model)
        tools = convert_tool_schema(param.tools)
        system = convert_system_to_input(param.system)

        stream = call_with_logged_payload(
            self.client.beta.messages.create,
            model=str(param.model),
            tool_choice={
                "type": "auto",
                "disable_parallel_tool_use": False,
            },
            stream=True,
            max_tokens=param.max_tokens or const.DEFAULT_MAX_TOKENS,
            temperature=param.temperature or const.DEFAULT_TEMPERATURE,
            messages=messages,
            system=system,
            tools=tools,
            betas=["interleaved-thinking-2025-05-14", "context-1m-2025-08-07"],
            thinking=anthropic.types.ThinkingConfigEnabledParam(
                type=param.thinking.type,
                budget_tokens=param.thinking.budget_tokens or const.DEFAULT_ANTHROPIC_THINKING_BUDGET_TOKENS,
            )
            if param.thinking and param.thinking.type == "enabled"
            else anthropic.types.ThinkingConfigDisabledParam(
                type="disabled",
            ),
            extra_headers={"extra": json.dumps({"session_id": param.session_id})},
        )

        accumulated_thinking: list[str] = []
        accumulated_content: list[str] = []
        response_id: str | None = None

        current_tool_name: str | None = None
        current_tool_call_id: str | None = None
        current_tool_inputs: list[str] | None = None

        input_tokens = 0
        cached_tokens = 0
        output_tokens = 0

        try:
            async for event in await stream:
                log_debug(
                    f"[{event.type}]",
                    event.model_dump_json(exclude_none=True),
                    style="blue",
                    debug_type=DebugType.LLM_STREAM,
                )
                match event:
                    case BetaRawMessageStartEvent() as event:
                        response_id = event.message.id
                        cached_tokens = event.message.usage.cache_read_input_tokens or 0
                        input_tokens = (event.message.usage.input_tokens or 0) + (
                            event.message.usage.cache_creation_input_tokens or 0
                        )
                        output_tokens = event.message.usage.output_tokens or 0
                        yield model.StartItem(response_id=response_id)
                    case BetaRawContentBlockDeltaEvent() as event:
                        match event.delta:
                            case BetaThinkingDelta() as delta:
                                if first_token_time is None:
                                    first_token_time = time.time()
                                last_token_time = time.time()
                                accumulated_thinking.append(delta.thinking)
                            case BetaSignatureDelta() as delta:
                                if first_token_time is None:
                                    first_token_time = time.time()
                                last_token_time = time.time()
                                yield model.ReasoningEncryptedItem(
                                    encrypted_content=delta.signature,
                                    response_id=response_id,
                                    model=str(param.model),
                                )
                            case BetaTextDelta() as delta:
                                if first_token_time is None:
                                    first_token_time = time.time()
                                last_token_time = time.time()
                                accumulated_content.append(delta.text)
                                yield model.AssistantMessageDelta(
                                    content=delta.text,
                                    response_id=response_id,
                                )
                            case BetaInputJSONDelta() as delta:
                                if first_token_time is None:
                                    first_token_time = time.time()
                                last_token_time = time.time()
                                if current_tool_inputs is not None:
                                    current_tool_inputs.append(delta.partial_json)
                            case _:
                                pass
                    case BetaRawContentBlockStartEvent() as event:
                        match event.content_block:
                            case BetaToolUseBlock() as block:
                                current_tool_name = block.name
                                current_tool_call_id = block.id
                                current_tool_inputs = []
                            case _:
                                pass
                    case BetaRawContentBlockStopEvent() as event:
                        if len(accumulated_thinking) > 0:
                            full_thinking = "".join(accumulated_thinking)
                            yield model.ReasoningTextItem(
                                content=full_thinking,
                                response_id=response_id,
                                model=str(param.model),
                            )
                            accumulated_thinking.clear()
                        if len(accumulated_content) > 0:
                            yield model.AssistantMessageItem(
                                content="".join(accumulated_content),
                                response_id=response_id,
                            )
                            accumulated_content.clear()
                        if current_tool_name and current_tool_call_id:
                            yield model.ToolCallItem(
                                name=current_tool_name,
                                call_id=current_tool_call_id,
                                arguments="".join(current_tool_inputs) if current_tool_inputs else "",
                                response_id=response_id,
                            )
                            current_tool_name = None
                            current_tool_call_id = None
                            current_tool_inputs = None
                    case BetaRawMessageDeltaEvent() as event:
                        input_tokens += (event.usage.input_tokens or 0) + (event.usage.cache_creation_input_tokens or 0)
                        output_tokens += event.usage.output_tokens or 0
                        cached_tokens += event.usage.cache_read_input_tokens or 0
                        total_tokens = input_tokens + cached_tokens + output_tokens
                        context_usage_percent = (
                            (total_tokens / param.context_limit) * 100 if param.context_limit else None
                        )

                        throughput_tps: float | None = None
                        first_token_latency_ms: float | None = None

                        if first_token_time is not None:
                            first_token_latency_ms = (first_token_time - request_start_time) * 1000

                        if first_token_time is not None and last_token_time is not None and output_tokens > 0:
                            time_duration = last_token_time - first_token_time
                            if time_duration >= 0.15:
                                throughput_tps = output_tokens / time_duration

                        yield model.ResponseMetadataItem(
                            usage=model.Usage(
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                cached_tokens=cached_tokens,
                                total_tokens=total_tokens,
                                context_usage_percent=context_usage_percent,
                                throughput_tps=throughput_tps,
                                first_token_latency_ms=first_token_latency_ms,
                            ),
                            response_id=response_id,
                            model_name=str(param.model),
                        )
                    case _:
                        pass
        except RateLimitError as e:
            yield StreamErrorItem(error=f"{e.__class__.__name__} {str(e)}")
