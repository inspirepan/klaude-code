import json
import os
from collections.abc import AsyncGenerator
from typing import Any, override

import anthropic
import httpx
from anthropic import APIError
from anthropic.types.beta import BetaTextBlockParam
from anthropic.types.beta.beta_input_json_delta import BetaInputJSONDelta
from anthropic.types.beta.beta_raw_content_block_delta_event import BetaRawContentBlockDeltaEvent
from anthropic.types.beta.beta_raw_content_block_start_event import BetaRawContentBlockStartEvent
from anthropic.types.beta.beta_raw_content_block_stop_event import BetaRawContentBlockStopEvent
from anthropic.types.beta.beta_raw_message_delta_event import BetaRawMessageDeltaEvent
from anthropic.types.beta.beta_raw_message_start_event import BetaRawMessageStartEvent
from anthropic.types.beta.beta_signature_delta import BetaSignatureDelta
from anthropic.types.beta.beta_text_delta import BetaTextDelta
from anthropic.types.beta.beta_thinking_delta import BetaThinkingDelta
from anthropic.types.beta.beta_tool_choice_auto_param import BetaToolChoiceAutoParam
from anthropic.types.beta.beta_tool_use_block import BetaToolUseBlock
from anthropic.types.beta.message_create_params import MessageCreateParamsStreaming

from klaude_code.const import (
    ANTHROPIC_BETA_INTERLEAVED_THINKING,
    CLAUDE_CODE_IDENTITY,
    DEFAULT_ANTHROPIC_THINKING_BUDGET_TOKENS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    LLM_HTTP_TIMEOUT_CONNECT,
    LLM_HTTP_TIMEOUT_READ,
    LLM_HTTP_TIMEOUT_TOTAL,
)
from klaude_code.llm.anthropic.input import convert_history_to_input, convert_system_to_input, convert_tool_schema
from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, error_stream_items
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import llm_param, message, model


def _map_anthropic_stop_reason(reason: str) -> model.StopReason | None:
    mapping: dict[str, model.StopReason] = {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "tool_use": "tool_use",
        "content_filter": "error",
        "error": "error",
        "cancelled": "aborted",
        "canceled": "aborted",
        "aborted": "aborted",
    }
    return mapping.get(reason)


def build_payload(
    param: llm_param.LLMCallParameter,
    *,
    extra_betas: list[str] | None = None,
) -> MessageCreateParamsStreaming:
    """Build Anthropic API request parameters.

    Args:
        param: LLM call parameters.
        extra_betas: Additional beta flags to prepend to the betas list.
    """
    messages = convert_history_to_input(param.input, param.model)
    tools = convert_tool_schema(param.tools)
    system_messages = [msg for msg in param.input if isinstance(msg, message.SystemMessage)]
    system = convert_system_to_input(param.system, system_messages)

    # Add identity block at the beginning of the system prompt
    identity_block: BetaTextBlockParam = {
        "type": "text",
        "text": CLAUDE_CODE_IDENTITY,
        "cache_control": {"type": "ephemeral"},
    }
    system = [identity_block, *system]

    betas = [ANTHROPIC_BETA_INTERLEAVED_THINKING]
    if extra_betas:
        # Prepend extra betas, avoiding duplicates
        betas = [b for b in extra_betas if b not in betas] + betas

    tool_choice: BetaToolChoiceAutoParam = {
        "type": "auto",
        "disable_parallel_tool_use": False,
    }

    payload: MessageCreateParamsStreaming = {
        "model": str(param.model),
        "tool_choice": tool_choice,
        "stream": True,
        "max_tokens": param.max_tokens or DEFAULT_MAX_TOKENS,
        "temperature": param.temperature or DEFAULT_TEMPERATURE,
        "messages": messages,
        "system": system,
        "tools": tools,
        "betas": betas,
    }

    if param.thinking and param.thinking.type == "enabled":
        payload["thinking"] = anthropic.types.ThinkingConfigEnabledParam(
            type="enabled",
            budget_tokens=param.thinking.budget_tokens or DEFAULT_ANTHROPIC_THINKING_BUDGET_TOKENS,
        )

    return payload


async def parse_anthropic_stream(
    stream: Any,
    param: llm_param.LLMCallParameter,
    metadata_tracker: MetadataTracker,
) -> AsyncGenerator[message.LLMStreamItem]:
    """Parse Anthropic beta messages stream and yield stream items."""
    accumulated_thinking: list[str] = []
    accumulated_content: list[str] = []
    parts: list[message.Part] = []
    response_id: str | None = None
    stop_reason: model.StopReason | None = None
    pending_signature: str | None = None

    current_tool_name: str | None = None
    current_tool_call_id: str | None = None
    current_tool_inputs: list[str] | None = None

    input_token = 0
    cached_token = 0

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
            case BetaRawContentBlockDeltaEvent() as event:
                match event.delta:
                    case BetaThinkingDelta() as delta:
                        if delta.thinking:
                            metadata_tracker.record_token()
                        accumulated_thinking.append(delta.thinking)
                        yield message.ThinkingTextDelta(
                            content=delta.thinking,
                            response_id=response_id,
                        )
                    case BetaSignatureDelta() as delta:
                        pending_signature = delta.signature
                    case BetaTextDelta() as delta:
                        if delta.text:
                            metadata_tracker.record_token()
                        accumulated_content.append(delta.text)
                        yield message.AssistantTextDelta(
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
                        yield message.ToolCallStartDelta(
                            response_id=response_id,
                            call_id=block.id,
                            name=block.name,
                        )
                        current_tool_name = block.name
                        current_tool_call_id = block.id
                        current_tool_inputs = []
                    case _:
                        pass
            case BetaRawContentBlockStopEvent():
                if accumulated_thinking:
                    metadata_tracker.record_token()
                    full_thinking = "".join(accumulated_thinking)
                    parts.append(message.ThinkingTextPart(text=full_thinking, model_id=str(param.model)))
                    if pending_signature:
                        parts.append(
                            message.ThinkingSignaturePart(
                                signature=pending_signature,
                                model_id=str(param.model),
                                format="anthropic",
                            )
                        )
                    accumulated_thinking.clear()
                    pending_signature = None
                if accumulated_content:
                    metadata_tracker.record_token()
                    parts.append(message.TextPart(text="".join(accumulated_content)))
                    accumulated_content.clear()
                if current_tool_name and current_tool_call_id:
                    metadata_tracker.record_token()
                    parts.append(
                        message.ToolCallPart(
                            call_id=current_tool_call_id,
                            tool_name=current_tool_name,
                            arguments_json="".join(current_tool_inputs) if current_tool_inputs else "",
                        )
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
                raw_stop_reason = getattr(event, "stop_reason", None)
                if isinstance(raw_stop_reason, str):
                    stop_reason = _map_anthropic_stop_reason(raw_stop_reason)
            case _:
                pass

    metadata = metadata_tracker.finalize()
    yield message.AssistantMessage(
        parts=parts,
        response_id=response_id,
        usage=metadata,
        stop_reason=stop_reason,
    )


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
                timeout=httpx.Timeout(
                    LLM_HTTP_TIMEOUT_TOTAL, connect=LLM_HTTP_TIMEOUT_CONNECT, read=LLM_HTTP_TIMEOUT_READ
                ),
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
    async def call(self, param: llm_param.LLMCallParameter) -> AsyncGenerator[message.LLMStreamItem]:
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

        try:
            async for item in parse_anthropic_stream(stream, param, metadata_tracker):
                yield item
        except (APIError, httpx.HTTPError) as e:
            error_message = f"{e.__class__.__name__} {e!s}"
            for item in error_stream_items(metadata_tracker, error=error_message):
                yield item
