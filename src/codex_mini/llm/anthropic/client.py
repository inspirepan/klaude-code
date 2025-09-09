from collections.abc import AsyncGenerator
from typing import override

import anthropic
import httpx
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

from codex_mini.llm.anthropic.input import convert_history_to_input, convert_system_to_input, convert_tool_schema
from codex_mini.llm.client import LLMClientABC
from codex_mini.llm.registry import register
from codex_mini.protocol import llm_parameter, model
from codex_mini.protocol.llm_parameter import (
    LLMCallParameter,
    LLMClientProtocol,
    LLMConfigParameter,
    apply_config_defaults,
)
from codex_mini.trace import log_debug


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

        messages = convert_history_to_input(param.input, param.model)
        tools = convert_tool_schema(param.tools)
        system = convert_system_to_input(param.system)

        if self.is_debug_mode():
            import json

            log_debug("▷▷▷ llm [Payload Messages]", json.dumps(messages, indent=2, ensure_ascii=False), style="yellow")

        stream = self.client.beta.messages.create(
            model=str(param.model),
            tool_choice={
                "type": "auto",
                "disable_parallel_tool_use": False,
            },
            stream=True,
            max_tokens=param.max_tokens or llm_parameter.DEFAULT_MAX_TOKENS,
            temperature=param.temperature or llm_parameter.DEFAULT_TEMPERATURE,
            messages=messages,
            system=system,
            tools=tools,
            betas=["interleaved-thinking-2025-05-14", "context-1m-2025-08-07"],
            thinking=anthropic.types.ThinkingConfigEnabledParam(
                type=param.thinking.type,
                budget_tokens=param.thinking.budget_tokens or llm_parameter.DEFAULT_ANTHROPIC_THINKING_BUDGET_TOKENS,
            )
            if param.thinking and param.thinking.type == "enabled"
            else anthropic.types.ThinkingConfigDisabledParam(
                type="disabled",
            ),
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

        async for event in await stream:
            if self.is_debug_mode():
                log_debug(f"◁◁◁ stream [SSE {event.type}]", str(event), style="blue")
            match event:
                case BetaRawMessageStartEvent() as event:
                    response_id = event.message.id
                    cached_tokens = event.message.usage.cache_read_input_tokens or 0
                    input_tokens = event.message.usage.input_tokens or 0
                    output_tokens = event.message.usage.output_tokens or 0
                    yield model.StartItem(response_id=response_id)
                case BetaRawContentBlockDeltaEvent() as event:
                    match event.delta:
                        case BetaThinkingDelta() as delta:
                            accumulated_thinking.append(delta.thinking)
                            yield model.ThinkingTextDelta(
                                thinking=delta.thinking,
                                response_id=response_id,
                            )
                        case BetaSignatureDelta() as delta:
                            full_thinking = "".join(accumulated_thinking)
                            accumulated_thinking.clear()
                            yield model.ThinkingTextItem(
                                thinking=full_thinking,
                                response_id=response_id,
                            )
                            yield model.ReasoningItem(
                                content=full_thinking,
                                encrypted_content=delta.signature,
                                response_id=response_id,
                                model=param.model,
                            )
                        case BetaTextDelta() as delta:
                            accumulated_content.append(delta.text)
                            yield model.AssistantMessageDelta(
                                content=delta.text,
                                response_id=response_id,
                            )
                        case BetaInputJSONDelta() as delta:
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
                    input_tokens += event.usage.input_tokens or 0
                    output_tokens += event.usage.output_tokens or 0
                    cached_tokens += event.usage.cache_read_input_tokens or 0
                    yield model.ResponseMetadataItem(
                        usage=model.Usage(
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            cached_tokens=cached_tokens,
                            total_tokens=input_tokens + output_tokens,
                        ),
                        response_id=response_id,
                        model_name=str(param.model),
                    )
                case _:
                    pass
