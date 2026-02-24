import json
from collections.abc import AsyncGenerator, AsyncIterable
from typing import TYPE_CHECKING, Any, cast, override

import httpx
import openai
from openai import AsyncAzureOpenAI, AsyncOpenAI
from openai._models import construct_type_unchecked
from openai.types import responses
from openai.types.responses.response_create_params import ResponseCreateParamsBase
from websockets.asyncio.client import ClientConnection as AsyncWebsocketConnection
from websockets.exceptions import ConnectionClosed, WebSocketException

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
    from openai.types.responses import ResponseStreamEvent


OPENAI_BETA_RESPONSES_WEBSOCKETS = "responses_websockets=2026-02-06"


def build_payload(
    param: llm_param.LLMCallParameter,
    *,
    is_volces_base_url: bool = False,
) -> ResponseCreateParamsBase:
    """Build OpenAI Responses API request parameters."""
    inputs = convert_history_to_input(
        param.input,
        param.model_id,
        function_call_output_string=is_volces_base_url,
        include_input_status=is_volces_base_url,
    )
    tools = convert_tool_schema(param.tools)

    payload: ResponseCreateParamsBase = {
        "model": str(param.model_id),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "store": False,
        "temperature": param.temperature,
        "max_output_tokens": param.max_tokens,
        "input": inputs,
        "instructions": param.system,
        "tools": tools,
    }

    if not is_volces_base_url:
        payload["prompt_cache_key"] = param.session_id or ""

    if not is_volces_base_url:
        payload["include"] = ["reasoning.encrypted_content"]

    if param.thinking and param.thinking.reasoning_effort:
        payload["reasoning"] = {
            "effort": param.thinking.reasoning_effort,
            "summary": param.thinking.reasoning_summary,
        }

    if param.verbosity:
        payload["text"] = {"verbosity": param.verbosity}  # type: ignore[typeddict-item]

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


class ResponsesWebSocketTransport:
    def __init__(
        self,
        client: AsyncOpenAI,
        connect_headers: dict[str, str] | None = None,
        connect_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self._client = client
        self._connection: AsyncWebsocketConnection | None = None
        self._connect_headers = connect_headers or {}
        self._connect_kwargs = connect_kwargs or {}

    def _prepare_url(self) -> httpx.URL:
        if self._client.websocket_base_url is not None:
            base_url = httpx.URL(self._client.websocket_base_url)
        else:
            base_url = self._client.base_url.copy_with(scheme="wss")
        return base_url.copy_with(raw_path=base_url.raw_path.rstrip(b"/") + b"/responses")

    async def _ensure_connection(self) -> AsyncWebsocketConnection:
        connection = self._connection
        if connection is not None:
            return connection

        from websockets.asyncio.client import connect

        headers = dict(self._client.auth_headers)
        if self._client.organization:
            headers["OpenAI-Organization"] = self._client.organization
        if self._client.project:
            headers["OpenAI-Project"] = self._client.project
        headers.update(self._connect_headers)
        headers.setdefault("OpenAI-Beta", OPENAI_BETA_RESPONSES_WEBSOCKETS)

        user_agent = headers.pop("User-Agent", self._client.user_agent)

        log_debug(
            "[responses websocket] connecting",
            str(self._prepare_url()),
            style="blue",
            debug_type=DebugType.LLM_STREAM,
        )
        self._connection = await connect(
            str(self._prepare_url()),
            user_agent_header=user_agent,
            additional_headers=headers,
            **self._connect_kwargs,
        )
        log_debug(
            "[responses websocket] connected",
            style="blue",
            debug_type=DebugType.LLM_STREAM,
        )
        return self._connection

    async def stream(self, payload: ResponseCreateParamsBase) -> AsyncGenerator[responses.ResponseStreamEvent]:
        connection = await self._ensure_connection()
        request = json.dumps({"type": "response.create", **payload})
        try:
            await connection.send(request)
        except ConnectionClosed:
            self._connection = None
            connection = await self._ensure_connection()
            await connection.send(request)

        try:
            while True:
                raw_message = await connection.recv(decode=False)
                raw_event = json.loads(raw_message)
                event = cast(
                    responses.ResponseStreamEvent,
                    construct_type_unchecked(value=raw_event, type_=cast(Any, responses.ResponseStreamEvent)),
                )
                yield event
                if raw_event.get("type") in {"response.completed", "response.failed", "response.incomplete", "error"}:
                    return
        except ConnectionClosed:
            self._connection = None
            raise


async def parse_responses_stream(
    stream: AsyncIterable["ResponseStreamEvent"],
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

    def record_response_done(response: responses.Response) -> str | None:
        error_reason: str | None = None
        if response.incomplete_details is not None:
            error_reason = response.incomplete_details.reason
        if response.usage is not None:
            metadata_tracker.set_usage(
                model.Usage(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cached_tokens=response.usage.input_tokens_details.cached_tokens,
                    reasoning_tokens=response.usage.output_tokens_details.reasoning_tokens,
                    context_size=response.usage.total_tokens,
                    context_limit=param.context_limit,
                    max_tokens=param.max_tokens,
                )
            )
        metadata_tracker.set_model_name(str(param.model_id))
        metadata_tracker.set_response_id(state.response_id)
        state.stop_reason = map_stop_reason(response.status, error_reason)
        return error_reason

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
                case responses.ResponseErrorEvent() as event:
                    nested_raw = getattr(event, "error", None)
                    nested: dict[str, object] | None = (
                        cast(dict[str, object], nested_raw) if isinstance(nested_raw, dict) else None
                    )
                    nested_message = nested.get("message") if nested else None
                    nested_code = nested.get("code") if nested else None
                    if not isinstance(nested_message, str):
                        nested_message = None
                    if not isinstance(nested_code, str):
                        nested_code = None
                    error_message = event.message or nested_message or "LLM response failed"
                    if event.code or nested_code:
                        error_message = f"{error_message} ({event.code or nested_code})"
                    yield message.StreamErrorItem(error=error_message)
                    state.stop_reason = "error"
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
                    error_reason = record_response_done(event.response)
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
                case responses.ResponseFailedEvent() as event:
                    record_response_done(event.response)
                    error_message = event.response.error.message if event.response.error else "LLM response failed"
                    yield message.StreamErrorItem(error=error_message)
                case responses.ResponseIncompleteEvent() as event:
                    error_reason = record_response_done(event.response)
                    error_message = "LLM response incomplete"
                    if error_reason:
                        error_message = f"{error_message}: {error_reason}"
                    yield message.StreamErrorItem(error=error_message)
                case _:
                    log_debug(
                        "[Unhandled stream event]",
                        str(event),
                        style="red",
                        debug_type=DebugType.LLM_STREAM,
                    )
    except (openai.OpenAIError, httpx.HTTPError, WebSocketException, json.JSONDecodeError, ImportError) as e:
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
        stream: AsyncIterable["ResponseStreamEvent"],
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
        self._is_volces_base_url = bool(config.base_url and "volces.com" in config.base_url.lower())
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
            ws_transport: ResponsesWebSocketTransport | None = None
        else:
            client = AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=httpx.Timeout(
                    LLM_HTTP_TIMEOUT_TOTAL, connect=LLM_HTTP_TIMEOUT_CONNECT, read=LLM_HTTP_TIMEOUT_READ
                ),
            )
            ws_transport = ResponsesWebSocketTransport(client) if not config.base_url else None
        self.client: AsyncAzureOpenAI | AsyncOpenAI = client
        self._ws_transport = ws_transport

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        payload = build_payload(param, is_volces_base_url=self._is_volces_base_url)

        log_debug(
            json.dumps(payload, ensure_ascii=False, default=str),
            style="yellow",
            debug_type=DebugType.LLM_PAYLOAD,
        )
        ws_transport = self._ws_transport
        if ws_transport is not None:
            log_debug(
                "[responses websocket] enabled",
                f"model={param.model_id}",
                style="yellow",
                debug_type=DebugType.LLM_CONFIG,
            )
            stream = ws_transport.stream(payload)
        else:
            try:
                stream = await self.client.responses.create(
                    **payload,
                    stream=True,
                    extra_headers={"extra": json.dumps({"session_id": param.session_id}, sort_keys=True)},
                )
            except (openai.OpenAIError, httpx.HTTPError) as e:
                error_message = f"{e.__class__.__name__} {e!s}"
                return error_llm_stream(metadata_tracker, error=error_message)

        return ResponsesLLMStream(stream, param=param, metadata_tracker=metadata_tracker)
