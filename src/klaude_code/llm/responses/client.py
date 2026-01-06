import json
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Literal, override

import httpx
import openai
from openai import AsyncAzureOpenAI, AsyncOpenAI
from openai.types import responses
from openai.types.responses.response_create_params import ResponseCreateParamsStreaming

from klaude_code.const import LLM_HTTP_TIMEOUT_CONNECT, LLM_HTTP_TIMEOUT_READ, LLM_HTTP_TIMEOUT_TOTAL
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.partial_message import degrade_thinking_to_text
from klaude_code.llm.registry import register
from klaude_code.llm.responses.input import convert_history_to_input, convert_tool_schema
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
    """Manages streaming state for Responses API and provides partial message access."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.response_id: str | None = None
        self.stage: Literal["waiting", "thinking", "assistant", "tool"] = "waiting"
        self.accumulated_thinking: list[str] = []
        self.accumulated_text: list[str] = []
        self.pending_signature: str | None = None
        self.assistant_parts: list[message.Part] = []
        self.stop_reason: model.StopReason | None = None

    def flush_thinking(self) -> None:
        """Flush accumulated thinking content into parts."""
        if self.accumulated_thinking:
            self.assistant_parts.append(
                message.ThinkingTextPart(
                    text="".join(self.accumulated_thinking),
                    model_id=self.model_id,
                )
            )
            self.accumulated_thinking.clear()
        if self.pending_signature:
            self.assistant_parts.append(
                message.ThinkingSignaturePart(
                    signature=self.pending_signature,
                    model_id=self.model_id,
                    format="openai_reasoning",
                )
            )
            self.pending_signature = None

    def flush_text(self) -> None:
        """Flush accumulated text content into parts."""
        if not self.accumulated_text:
            return
        self.assistant_parts.append(message.TextPart(text="".join(self.accumulated_text)))
        self.accumulated_text.clear()

    def flush_all(self) -> list[message.Part]:
        """Flush all accumulated content and return parts."""
        self.flush_thinking()
        self.flush_text()
        return list(self.assistant_parts)

    def get_partial_message(self) -> message.AssistantMessage | None:
        """Build a partial AssistantMessage from accumulated state."""
        parts = self.flush_all()
        filtered_parts: list[message.Part] = []
        for part in parts:
            if isinstance(part, message.ToolCallPart):
                continue
            filtered_parts.append(part)

        filtered_parts = degrade_thinking_to_text(filtered_parts)
        if not filtered_parts:
            return None
        return message.AssistantMessage(
            parts=filtered_parts,
            response_id=self.response_id,
            stop_reason="aborted",
        )


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
                case responses.ResponseReasoningSummaryTextDeltaEvent() as event:
                    if event.delta:
                        metadata_tracker.record_token()
                        if state.stage == "assistant":
                            state.flush_text()
                        state.stage = "thinking"
                        state.accumulated_thinking.append(event.delta)
                        yield message.ThinkingTextDelta(content=event.delta, response_id=state.response_id)
                case responses.ResponseReasoningSummaryTextDoneEvent() as event:
                    if event.text and not state.accumulated_thinking:
                        state.accumulated_thinking.append(event.text)
                case responses.ResponseTextDeltaEvent() as event:
                    if event.delta:
                        metadata_tracker.record_token()
                        if state.stage == "thinking":
                            state.flush_thinking()
                        state.stage = "assistant"
                        state.accumulated_text.append(event.delta)
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
                                state.pending_signature = item.encrypted_content
                        case responses.ResponseOutputMessage() as item:
                            if not state.accumulated_text:
                                text_content = "\n".join(
                                    [
                                        part.text
                                        for part in item.content
                                        if isinstance(part, responses.ResponseOutputText)
                                    ]
                                )
                                if text_content:
                                    state.accumulated_text.append(text_content)
                        case responses.ResponseFunctionToolCall() as item:
                            metadata_tracker.record_token()
                            state.flush_thinking()
                            state.flush_text()
                            state.stage = "tool"
                            state.assistant_parts.append(
                                message.ToolCallPart(
                                    call_id=item.call_id,
                                    id=item.id,
                                    tool_name=item.name,
                                    arguments_json=item.arguments.strip(),
                                )
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

    parts = state.flush_all()
    metadata_tracker.set_response_id(state.response_id)
    metadata = metadata_tracker.finalize()
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
