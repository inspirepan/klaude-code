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
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.registry import register
from klaude_code.llm.stream_parts import (
    append_text_part,
    append_thinking_text_part,
    build_partial_message,
    build_partial_parts,
)
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
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


class AnthropicStreamStateManager:
    """Manages streaming state for Anthropic API responses.

    Accumulates thinking, content, and tool call parts during streaming
    to support partial message retrieval on cancellation.
    """

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.assistant_parts: list[message.Part] = []
        self.response_id: str | None = None
        self._pending_signature: str | None = None
        self._pending_signature_thinking_index: int | None = None
        self.stop_reason: model.StopReason | None = None

        # Tool call state
        self.current_tool_name: str | None = None
        self.current_tool_call_id: str | None = None
        self.current_tool_inputs: list[str] | None = None

        # Token tracking
        self.input_token: int = 0
        self.cached_token: int = 0

    def append_thinking_text(self, text: str) -> None:
        """Append thinking text, merging with the previous ThinkingTextPart when possible."""
        index = append_thinking_text_part(self.assistant_parts, text, model_id=self.model_id)
        if index is not None:
            self._pending_signature_thinking_index = index

    def append_text(self, text: str) -> None:
        """Append assistant text, merging with the previous TextPart when possible."""
        append_text_part(self.assistant_parts, text)

    def set_pending_signature(self, signature: str) -> None:
        if signature:
            self._pending_signature = signature

    def flush_pending_signature(self) -> None:
        """Attach any pending signature to the most recent thinking segment.

        Anthropic's signature is semantically tied to its thinking content. The
        signature delta may arrive slightly after thinking text, so we insert the
        signature part adjacent to the thinking part it signs.
        """

        if not self._pending_signature:
            return
        if self._pending_signature_thinking_index is None:
            # No thinking part seen for this signature; drop it.
            self._pending_signature = None
            return

        insert_at = self._pending_signature_thinking_index + 1
        # Avoid inserting duplicates if flush is called multiple times.
        if insert_at < len(self.assistant_parts) and isinstance(
            self.assistant_parts[insert_at], message.ThinkingSignaturePart
        ):
            self._pending_signature = None
            return

        self.assistant_parts.insert(
            insert_at,
            message.ThinkingSignaturePart(
                signature=self._pending_signature,
                model_id=self.model_id,
                format="anthropic",
            ),
        )

        self._pending_signature = None
        self._pending_signature_thinking_index = None

    def flush_tool_call(self) -> None:
        """Flush current tool call into parts."""
        if self.current_tool_name and self.current_tool_call_id:
            self.assistant_parts.append(
                message.ToolCallPart(
                    call_id=self.current_tool_call_id,
                    tool_name=self.current_tool_name,
                    arguments_json="".join(self.current_tool_inputs) if self.current_tool_inputs else "",
                )
            )
        self.current_tool_name = None
        self.current_tool_call_id = None
        self.current_tool_inputs = None

    def flush_all(self) -> list[message.Part]:
        """Flush all pending content in order and return parts."""
        self.flush_pending_signature()
        self.flush_tool_call()
        return list(self.assistant_parts)

    def get_partial_parts(self) -> list[message.Part]:
        """Get accumulated parts excluding tool calls, with thinking degraded.

        Filters out ToolCallPart and applies degrade_thinking_to_text.
        """
        return build_partial_parts(self.assistant_parts)

    def get_partial_message(self) -> message.AssistantMessage | None:
        """Build a partial AssistantMessage from accumulated state.

        Flushes all accumulated content and returns the message with
        stop_reason="aborted". Returns None if no content has been accumulated.
        """
        return build_partial_message(self.assistant_parts, response_id=self.response_id)


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
    messages = convert_history_to_input(param.input, param.model_id)
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
        "model": str(param.model_id),
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
    state: AnthropicStreamStateManager,
) -> AsyncGenerator[message.LLMStreamItem]:
    """Parse Anthropic beta messages stream and yield stream items.

    The state parameter allows external access to accumulated content
    for cancellation scenarios.
    """
    async for event in await stream:
        log_debug(
            f"[{event.type}]",
            event.model_dump_json(exclude_none=True),
            style="blue",
            debug_type=DebugType.LLM_STREAM,
        )
        match event:
            case BetaRawMessageStartEvent() as event:
                state.response_id = event.message.id
                state.cached_token = event.message.usage.cache_read_input_tokens or 0
                state.input_token = event.message.usage.input_tokens
            case BetaRawContentBlockDeltaEvent() as event:
                match event.delta:
                    case BetaThinkingDelta() as delta:
                        if delta.thinking:
                            metadata_tracker.record_token()
                            state.append_thinking_text(delta.thinking)
                            yield message.ThinkingTextDelta(
                                content=delta.thinking,
                                response_id=state.response_id,
                            )
                    case BetaSignatureDelta() as delta:
                        state.set_pending_signature(delta.signature)
                    case BetaTextDelta() as delta:
                        if delta.text:
                            metadata_tracker.record_token()
                            state.flush_pending_signature()
                            state.append_text(delta.text)
                            yield message.AssistantTextDelta(
                                content=delta.text,
                                response_id=state.response_id,
                            )
                    case BetaInputJSONDelta() as delta:
                        if state.current_tool_inputs is not None and delta.partial_json:
                            metadata_tracker.record_token()
                            state.current_tool_inputs.append(delta.partial_json)
                    case _:
                        pass
            case BetaRawContentBlockStartEvent() as event:
                match event.content_block:
                    case BetaToolUseBlock() as block:
                        metadata_tracker.record_token()
                        state.flush_pending_signature()
                        yield message.ToolCallStartDelta(
                            response_id=state.response_id,
                            call_id=block.id,
                            name=block.name,
                        )
                        state.current_tool_name = block.name
                        state.current_tool_call_id = block.id
                        state.current_tool_inputs = []
                    case _:
                        pass
            case BetaRawContentBlockStopEvent():
                state.flush_pending_signature()
                if state.current_tool_name and state.current_tool_call_id:
                    metadata_tracker.record_token()
                    state.flush_tool_call()
            case BetaRawMessageDeltaEvent() as event:
                metadata_tracker.set_usage(
                    model.Usage(
                        input_tokens=state.input_token + state.cached_token,
                        output_tokens=event.usage.output_tokens,
                        cached_tokens=state.cached_token,
                        context_size=state.input_token + state.cached_token + event.usage.output_tokens,
                        context_limit=param.context_limit,
                        max_tokens=param.max_tokens,
                    )
                )
                raw_stop_reason = getattr(event, "stop_reason", None)
                if isinstance(raw_stop_reason, str):
                    state.stop_reason = _map_anthropic_stop_reason(raw_stop_reason)
            case _:
                pass

    parts = state.flush_all()
    if parts:
        metadata_tracker.record_token()
    metadata_tracker.set_model_name(str(param.model_id))
    metadata_tracker.set_response_id(state.response_id)
    metadata = metadata_tracker.finalize()
    yield message.AssistantMessage(
        parts=parts,
        response_id=state.response_id,
        usage=metadata,
        stop_reason=state.stop_reason,
    )


class AnthropicLLMStream(LLMStreamABC):
    """LLMStream implementation for Anthropic-compatible clients."""

    def __init__(
        self,
        stream: Any,
        *,
        param: llm_param.LLMCallParameter,
        metadata_tracker: MetadataTracker,
    ) -> None:
        self._stream = stream
        self._param = param
        self._metadata_tracker = metadata_tracker
        self._state = AnthropicStreamStateManager(model_id=str(param.model_id))
        self._completed = False

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        try:
            async for item in parse_anthropic_stream(
                self._stream,
                self._param,
                self._metadata_tracker,
                self._state,
            ):
                if isinstance(item, message.AssistantMessage):
                    self._completed = True
                yield item
        except (anthropic.AnthropicError, httpx.HTTPError) as e:
            yield message.StreamErrorItem(error=f"{e.__class__.__name__} {e!s}")
            self._metadata_tracker.set_model_name(str(self._param.model_id))
            self._metadata_tracker.set_response_id(self._state.response_id)
            metadata = self._metadata_tracker.finalize()
            # Use accumulated parts for potential prefill on retry
            self._state.flush_all()
            yield message.AssistantMessage(
                parts=self._state.get_partial_parts(),
                response_id=self._state.response_id,
                usage=metadata,
                stop_reason="error",
            )

    def get_partial_message(self) -> message.AssistantMessage | None:
        if self._completed:
            return None
        return self._state.get_partial_message()


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
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        payload = build_payload(param)

        log_debug(
            json.dumps(payload, ensure_ascii=False, default=str),
            style="yellow",
            debug_type=DebugType.LLM_PAYLOAD,
        )

        try:
            stream = self.client.beta.messages.create(
                **payload,
                extra_headers={"extra": json.dumps({"session_id": param.session_id}, sort_keys=True)},
            )
            return AnthropicLLMStream(stream, param=param, metadata_tracker=metadata_tracker)
        except (APIError, httpx.HTTPError) as e:
            error_message = f"{e.__class__.__name__} {e!s}"
            return error_llm_stream(metadata_tracker, error=error_message)
