import json
import os
from collections.abc import AsyncGenerator
from typing import override

import anthropic
import httpx
from anthropic import APIError
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
from anthropic.types.beta.message_create_params import MessageCreateParamsStreaming

from klaude_code import const
from klaude_code.llm.anthropic.input import convert_history_to_input, convert_system_to_input, convert_tool_schema
from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker
from klaude_code.protocol import llm_param, model
from klaude_code.trace import DebugType, log_debug


def build_payload(param: llm_param.LLMCallParameter) -> MessageCreateParamsStreaming:
    """Build Anthropic API request parameters."""
    messages = convert_history_to_input(param.input, param.model)
    tools = convert_tool_schema(param.tools)
    system = convert_system_to_input(param.system)

    payload: MessageCreateParamsStreaming = {
        "model": str(param.model),
        "tool_choice": {
            "type": "auto",
            "disable_parallel_tool_use": False,
        },
        "stream": True,
        "max_tokens": param.max_tokens or const.DEFAULT_MAX_TOKENS,
        "temperature": param.temperature or const.DEFAULT_TEMPERATURE,
        "messages": messages,
        "system": system,
        "tools": tools,
        "betas": ["interleaved-thinking-2025-05-14", "context-1m-2025-08-07"],
    }

    if param.thinking and param.thinking.type == "enabled":
        payload["thinking"] = anthropic.types.ThinkingConfigEnabledParam(
            type="enabled",
            budget_tokens=param.thinking.budget_tokens or const.DEFAULT_ANTHROPIC_THINKING_BUDGET_TOKENS,
        )

    return payload


@register(llm_param.LLMClientProtocol.ANTHROPIC)
class AnthropicClient(LLMClientABC):
    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        # Remove ANTHROPIC_AUTH_TOKEN env var to prevent anthropic SDK from adding
        # Authorization: Bearer header that may conflict with third-party APIs
        # (e.g., deepseek, moonshot) that use Authorization header for authentication.
        # The API key will be sent via X-Api-Key header instead.
        saved_auth_token = os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        try:
            client = anthropic.AsyncAnthropic(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=httpx.Timeout(300.0, connect=15.0, read=285.0),
            )
        finally:
            if saved_auth_token is not None:
                os.environ["ANTHROPIC_AUTH_TOKEN"] = saved_auth_token
        self.client: anthropic.AsyncAnthropic = client

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> AsyncGenerator[model.ConversationItem]:
        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        payload = build_payload(param)

        log_debug(
            json.dumps(payload, ensure_ascii=False, default=str),
            style="yellow",
            debug_type=DebugType.LLM_PAYLOAD,
        )

        stream = self.client.beta.messages.create(
            **payload,
            extra_headers={"extra": json.dumps({"session_id": param.session_id}, sort_keys=True)},
        )

        accumulated_thinking: list[str] = []
        accumulated_content: list[str] = []
        response_id: str | None = None

        current_tool_name: str | None = None
        current_tool_call_id: str | None = None
        current_tool_inputs: list[str] | None = None

        input_token = 0
        cached_token = 0

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
                        cached_token = event.message.usage.cache_read_input_tokens or 0
                        input_token = event.message.usage.input_tokens
                        yield model.StartItem(response_id=response_id)
                    case BetaRawContentBlockDeltaEvent() as event:
                        match event.delta:
                            case BetaThinkingDelta() as delta:
                                if delta.thinking:
                                    metadata_tracker.record_token()
                                accumulated_thinking.append(delta.thinking)
                                yield model.ReasoningTextDelta(
                                    content=delta.thinking,
                                    response_id=response_id,
                                )
                            case BetaSignatureDelta() as delta:
                                yield model.ReasoningEncryptedItem(
                                    encrypted_content=delta.signature,
                                    response_id=response_id,
                                    model=str(param.model),
                                )
                            case BetaTextDelta() as delta:
                                if delta.text:
                                    metadata_tracker.record_token()
                                accumulated_content.append(delta.text)
                                yield model.AssistantMessageDelta(
                                    content=delta.text,
                                    response_id=response_id,
                                )
                            case BetaInputJSONDelta() as delta:
                                if current_tool_inputs is not None:
                                    if delta.partial_json:
                                        metadata_tracker.record_token()
                                    current_tool_inputs.append(delta.partial_json)
                            case _:
                                pass
                    case BetaRawContentBlockStartEvent() as event:
                        match event.content_block:
                            case BetaToolUseBlock() as block:
                                metadata_tracker.record_token()
                                yield model.ToolCallStartItem(
                                    response_id=response_id,
                                    call_id=block.id,
                                    name=block.name,
                                )
                                current_tool_name = block.name
                                current_tool_call_id = block.id
                                current_tool_inputs = []
                            case _:
                                pass
                    case BetaRawContentBlockStopEvent() as event:
                        if len(accumulated_thinking) > 0:
                            metadata_tracker.record_token()
                            full_thinking = "".join(accumulated_thinking)
                            yield model.ReasoningTextItem(
                                content=full_thinking,
                                response_id=response_id,
                                model=str(param.model),
                            )
                            accumulated_thinking.clear()
                        if len(accumulated_content) > 0:
                            metadata_tracker.record_token()
                            yield model.AssistantMessageItem(
                                content="".join(accumulated_content),
                                response_id=response_id,
                            )
                            accumulated_content.clear()
                        if current_tool_name and current_tool_call_id:
                            metadata_tracker.record_token()
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
                        metadata_tracker.set_usage(
                            model.Usage(
                                input_tokens=input_token + cached_token,
                                output_tokens=event.usage.output_tokens,
                                cached_tokens=cached_token,
                                context_size=input_token + cached_token + event.usage.output_tokens,
                                context_limit=param.context_limit,
                                max_tokens=param.max_tokens,
                            )
                        )
                        metadata_tracker.set_model_name(str(param.model))
                        metadata_tracker.set_response_id(response_id)
                        yield metadata_tracker.finalize()
                    case _:
                        pass
        except (APIError, httpx.HTTPError) as e:
            yield model.StreamErrorItem(error=f"{e.__class__.__name__} {e!s}")
