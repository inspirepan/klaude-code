import json
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, override

import httpx
import openai
from openai import AsyncAzureOpenAI, AsyncOpenAI
from openai.types import responses
from openai.types.responses.response_create_params import ResponseCreateParamsStreaming

from klaude_code.const import LLM_HTTP_TIMEOUT_CONNECT, LLM_HTTP_TIMEOUT_READ, LLM_HTTP_TIMEOUT_TOTAL
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.openai_responses.input import convert_history_to_input, convert_tool_schema
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

if TYPE_CHECKING:
    from openai import AsyncStream
    from openai.types.responses import ResponseStreamEvent


def build_payload(param: llm_param.LLMCallParameter) -> ResponseCreateParamsStreaming:
    """Build OpenAI Responses API request parameters."""
    inputs = convert_history_to_input(param.input, param.model_id)
    tools = convert_tool_schema(param.tools)

    payload: ResponseCreateParamsStreaming = {
        "model": str(param.model_id),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "include": [
            "reasoning.encrypted_content",
        ],
        "store": False,
        "stream": True,
        "temperature": param.temperature,
        "max_output_tokens": param.max_tokens,
        "input": inputs,
        "instructions": param.system,
        "tools": tools,
        "prompt_cache_key": param.session_id or "",
    }

    if param.thinking and param.thinking.reasoning_effort:
        payload["reasoning"] = {
            "effort": param.thinking.reasoning_effort,
            "summary": param.thinking.reasoning_summary,
        }

    if param.verbosity:
        payload["text"] = {"verbosity": param.verbosity}

    return payload


class ResponsesStreamStateManager:
    """Manages streaming state for Responses API and provides partial message access.

    Accumulates parts directly during streaming to support get_partial_message()
    for cancellation scenarios. Merges consecutive text parts of the same type.
    Each reasoning summary is kept as a separate ThinkingTextPart.
    """

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.response_id: str | None = None
        self.assistant_parts: list[message.Part] = []
        self.stop_reason: model.StopReason | None = None
        self._new_thinking_part: bool = True  # Start fresh for first thinking part
        self._summary_count: int = 0  # Track number of summary parts seen

    def start_new_thinking_part(self) -> bool:
        """Mark that the next thinking text should create a new ThinkingTextPart.

        Returns True if this is not the first summary part (needs separator).
        """
        self._new_thinking_part = True
        needs_separator = self._summary_count > 0
        self._summary_count += 1
        return needs_separator

    def append_thinking_text(self, text: str) -> None:
        """Append thinking text, merging with previous ThinkingTextPart if in same summary."""
        if (
            append_thinking_text_part(
                self.assistant_parts,
                text,
                model_id=self.model_id,
                force_new=self._new_thinking_part,
            )
            is not None
        ):
            self._new_thinking_part = False

    def append_text(self, text: str) -> None:
        """Append text, merging with previous TextPart if possible."""
        append_text_part(self.assistant_parts, text)

    def append_thinking_signature(self, signature: str) -> None:
        """Append a ThinkingSignaturePart after the current part."""
        self.assistant_parts.append(
            message.ThinkingSignaturePart(
                signature=signature,
                model_id=self.model_id,
                format="openai-responses",
            )
        )

    def append_tool_call(self, call_id: str, item_id: str | None, name: str, arguments_json: str) -> None:
        """Append a ToolCallPart."""
        self.assistant_parts.append(
            message.ToolCallPart(
                call_id=call_id,
                id=item_id,
                tool_name=name,
                arguments_json=arguments_json,
            )
        )

    def get_partial_parts(self) -> list[message.Part]:
        """Get accumulated parts excluding tool calls, with thinking degraded.

        Filters out ToolCallPart and applies degrade_thinking_to_text.
        """
        return build_partial_parts(self.assistant_parts)

    def get_partial_message(self) -> message.AssistantMessage | None:
        """Build a partial AssistantMessage from accumulated state.

        Returns None if no content has been accumulated yet.
        """
        return build_partial_message(self.assistant_parts, response_id=self.response_id)


async def parse_responses_stream(
    stream: "AsyncStream[ResponseStreamEvent]",
    *,
    state: ResponsesStreamStateManager,
    param: llm_param.LLMCallParameter,
    metadata_tracker: MetadataTracker,
) -> AsyncGenerator[message.LLMStreamItem]:
    """Parse OpenAI Responses API stream events into stream items."""

    def map_stop_reason(status: str | None, reason: str | None) -> model.StopReason | None:
        if reason:
            normalized = reason.strip().lower()
            if normalized in {"max_output_tokens", "length", "max_tokens"}:
                return "length"
            if normalized in {"content_filter", "safety"}:
                return "error"
            if normalized in {"cancelled", "canceled", "aborted"}:
                return "aborted"
        if status == "completed":
            return "stop"
        if status in {"failed", "error"}:
            return "error"
        return None

    try:
        async for event in stream:
            log_debug(
                f"[{event.type}]",
                event.model_dump_json(exclude_none=True),
                style="blue",
                debug_type=DebugType.LLM_STREAM,
            )
            match event:
                case responses.ResponseCreatedEvent() as event:
                    state.response_id = event.response.id
                case responses.ResponseReasoningSummaryPartAddedEvent():
                    # New reasoning summary part started, ensure it becomes a new ThinkingTextPart
                    needs_separator = state.start_new_thinking_part()
                    if needs_separator:
                        # Add blank lines between summary parts for visual separation
                        yield message.ThinkingTextDelta(content="  \n  \n", response_id=state.response_id)
                case responses.ResponseReasoningSummaryTextDeltaEvent() as event:
                    if event.delta:
                        metadata_tracker.record_token()
                        state.append_thinking_text(event.delta)
                        yield message.ThinkingTextDelta(content=event.delta, response_id=state.response_id)
                case responses.ResponseReasoningSummaryTextDoneEvent() as event:
                    # Fallback: if no delta was received but done has full text, use it
                    if event.text:
                        # Check if we already have content for this summary by seeing if last part matches
                        last_part = state.assistant_parts[-1] if state.assistant_parts else None
                        if not isinstance(last_part, message.ThinkingTextPart) or not last_part.text:
                            state.append_thinking_text(event.text)
                case responses.ResponseTextDeltaEvent() as event:
                    if event.delta:
                        metadata_tracker.record_token()
                        state.append_text(event.delta)
                        yield message.AssistantTextDelta(content=event.delta, response_id=state.response_id)
                case responses.ResponseOutputItemAddedEvent() as event:
                    if isinstance(event.item, responses.ResponseFunctionToolCall):
                        metadata_tracker.record_token()
                        yield message.ToolCallStartDelta(
                            response_id=state.response_id,
                            call_id=event.item.call_id,
                            name=event.item.name,
                        )
                case responses.ResponseOutputItemDoneEvent() as event:
                    match event.item:
                        case responses.ResponseReasoningItem() as item:
                            if item.encrypted_content:
                                state.append_thinking_signature(item.encrypted_content)
                        case responses.ResponseOutputMessage() as item:
                            # Fallback: if no text delta was received, extract from final message
                            has_text = any(isinstance(p, message.TextPart) for p in state.assistant_parts)
                            if not has_text:
                                text_content = "\n".join(
                                    part.text for part in item.content if isinstance(part, responses.ResponseOutputText)
                                )
                                if text_content:
                                    state.append_text(text_content)
                        case responses.ResponseFunctionToolCall() as item:
                            metadata_tracker.record_token()
                            state.append_tool_call(
                                call_id=item.call_id,
                                item_id=item.id,
                                name=item.name,
                                arguments_json=item.arguments.strip(),
                            )
                        case _:
                            pass
                case responses.ResponseCompletedEvent() as event:
                    error_reason: str | None = None
                    if event.response.incomplete_details is not None:
                        error_reason = event.response.incomplete_details.reason
                    if event.response.usage is not None:
                        metadata_tracker.set_usage(
                            model.Usage(
                                input_tokens=event.response.usage.input_tokens,
                                output_tokens=event.response.usage.output_tokens,
                                cached_tokens=event.response.usage.input_tokens_details.cached_tokens,
                                reasoning_tokens=event.response.usage.output_tokens_details.reasoning_tokens,
                                context_size=event.response.usage.total_tokens,
                                context_limit=param.context_limit,
                                max_tokens=param.max_tokens,
                            )
                        )
                    metadata_tracker.set_model_name(str(param.model_id))
                    metadata_tracker.set_response_id(state.response_id)
                    state.stop_reason = map_stop_reason(event.response.status, error_reason)
                    if event.response.status != "completed":
                        error_message = f"LLM response finished with status '{event.response.status}'"
                        if error_reason:
                            error_message = f"{error_message}: {error_reason}"
                        log_debug(
                            "[LLM status warning]",
                            error_message,
                            style="red",
                            debug_type=DebugType.LLM_STREAM,
                        )
                        yield message.StreamErrorItem(error=error_message)
                case _:
                    log_debug(
                        "[Unhandled stream event]",
                        str(event),
                        style="red",
                        debug_type=DebugType.LLM_STREAM,
                    )
    except (openai.OpenAIError, httpx.HTTPError) as e:
        yield message.StreamErrorItem(error=f"{e.__class__.__name__} {e!s}")
        state.stop_reason = "error"

    metadata_tracker.set_response_id(state.response_id)
    metadata = metadata_tracker.finalize()
    # On error, use partial parts (excluding incomplete tool calls) for potential prefill on retry
    parts = state.get_partial_parts() if state.stop_reason == "error" else list(state.assistant_parts)
    yield message.AssistantMessage(
        parts=parts,
        response_id=state.response_id,
        usage=metadata,
        stop_reason=state.stop_reason,
    )


class ResponsesLLMStream(LLMStreamABC):
    """LLMStream implementation for Responses API clients."""

    def __init__(
        self,
        stream: "AsyncStream[ResponseStreamEvent]",
        *,
        param: llm_param.LLMCallParameter,
        metadata_tracker: MetadataTracker,
    ) -> None:
        self._stream = stream
        self._param = param
        self._metadata_tracker = metadata_tracker
        self._state = ResponsesStreamStateManager(str(param.model_id))
        self._completed = False

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        async for item in parse_responses_stream(
            self._stream,
            state=self._state,
            param=self._param,
            metadata_tracker=self._metadata_tracker,
        ):
            if isinstance(item, message.AssistantMessage):
                self._completed = True
            yield item

    def get_partial_message(self) -> message.AssistantMessage | None:
        if self._completed:
            return None
        return self._state.get_partial_message()


@register(llm_param.LLMClientProtocol.RESPONSES)
class ResponsesClient(LLMClientABC):
    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        if config.is_azure:
            if not config.base_url:
                raise ValueError("Azure endpoint is required")
            client = AsyncAzureOpenAI(
                api_key=config.api_key,
                azure_endpoint=str(config.base_url),
                api_version=config.azure_api_version,
                timeout=httpx.Timeout(
                    LLM_HTTP_TIMEOUT_TOTAL, connect=LLM_HTTP_TIMEOUT_CONNECT, read=LLM_HTTP_TIMEOUT_READ
                ),
            )
        else:
            client = AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=httpx.Timeout(
                    LLM_HTTP_TIMEOUT_TOTAL, connect=LLM_HTTP_TIMEOUT_CONNECT, read=LLM_HTTP_TIMEOUT_READ
                ),
            )
        self.client: AsyncAzureOpenAI | AsyncOpenAI = client

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
            stream = await self.client.responses.create(
                **payload,
                extra_headers={"extra": json.dumps({"session_id": param.session_id}, sort_keys=True)},
            )
        except (openai.OpenAIError, httpx.HTTPError) as e:
            error_message = f"{e.__class__.__name__} {e!s}"
            return error_llm_stream(metadata_tracker, error=error_message)

        return ResponsesLLMStream(stream, param=param, metadata_tracker=metadata_tracker)
