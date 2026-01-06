# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportAttributeAccessIssue=false

import json
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, Literal, cast, override
from uuid import uuid4

import httpx
from google.genai import Client
from google.genai.errors import APIError, ClientError, ServerError
from google.genai.types import (
    FunctionCallingConfig,
    FunctionCallingConfigMode,
    GenerateContentConfig,
    HttpOptions,
    ThinkingConfig,
    ToolConfig,
    UsageMetadata,
)

from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.google.input import convert_history_to_contents, convert_tool_schema
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.partial_message import degrade_thinking_to_text
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import llm_param, message, model


def _build_config(param: llm_param.LLMCallParameter) -> GenerateContentConfig:
    tool_list = convert_tool_schema(param.tools)
    tool_config: ToolConfig | None = None

    if tool_list:
        tool_config = ToolConfig(
            function_calling_config=FunctionCallingConfig(
                mode=FunctionCallingConfigMode.AUTO,
                # Gemini streams tool args; keep this enabled to maximize fidelity.
                stream_function_call_arguments=True,
            )
        )

    thinking_config: ThinkingConfig | None = None
    if param.thinking and param.thinking.type == "enabled":
        thinking_config = ThinkingConfig(
            include_thoughts=True,
            thinking_budget=param.thinking.budget_tokens,
        )

    return GenerateContentConfig(
        system_instruction=param.system,
        temperature=param.temperature,
        max_output_tokens=param.max_tokens,
        tools=cast(Any, tool_list) if tool_list else None,
        tool_config=tool_config,
        thinking_config=thinking_config,
    )


def _usage_from_metadata(
    usage: UsageMetadata | None,
    *,
    context_limit: int | None,
    max_tokens: int | None,
) -> model.Usage | None:
    if usage is None:
        return None

    cached = usage.cached_content_token_count or 0
    prompt = usage.prompt_token_count or 0
    response = usage.response_token_count or 0
    thoughts = usage.thoughts_token_count or 0

    total = usage.total_token_count
    if total is None:
        total = prompt + cached + response + thoughts

    return model.Usage(
        input_tokens=prompt + cached,
        cached_tokens=cached,
        output_tokens=response + thoughts,
        reasoning_tokens=thoughts,
        context_size=total,
        context_limit=context_limit,
        max_tokens=max_tokens,
    )


def _partial_arg_value(partial: Any) -> Any:
    if getattr(partial, "string_value", None) is not None:
        return partial.string_value
    if getattr(partial, "number_value", None) is not None:
        return partial.number_value
    if getattr(partial, "bool_value", None) is not None:
        return partial.bool_value
    if getattr(partial, "null_value", None) is not None:
        return None
    return None


def _merge_partial_args(dst: dict[str, Any], partial_args: list[Any] | None) -> None:
    if not partial_args:
        return
    for partial in partial_args:
        json_path = getattr(partial, "json_path", None)
        if not isinstance(json_path, str) or not json_path.startswith("$."):
            continue
        key = json_path[2:]
        if not key or any(ch in key for ch in "[]"):
            continue
        dst[key] = _partial_arg_value(partial)


def _map_finish_reason(reason: str) -> model.StopReason | None:
    normalized = reason.strip().lower()
    mapping: dict[str, model.StopReason] = {
        "stop": "stop",
        "end_turn": "stop",
        "max_tokens": "length",
        "length": "length",
        "tool_use": "tool_use",
        "safety": "error",
        "recitation": "error",
        "other": "error",
        "content_filter": "error",
        "blocked": "error",
        "blocklist": "error",
        "cancelled": "aborted",
        "canceled": "aborted",
        "aborted": "aborted",
    }
    return mapping.get(normalized)


class GoogleStreamStateManager:
    """Manages streaming state for Google LLM responses.

    Accumulates thinking content, assistant text, and tool calls during streaming
    to support get_partial_message() for cancellation scenarios.
    """

    def __init__(self, param_model: str) -> None:
        self.param_model = param_model
        self.accumulated_thoughts: list[str] = []
        self.accumulated_text: list[str] = []
        self.thought_signature: str | None = None
        self.assistant_parts: list[message.Part] = []
        self.response_id: str | None = None
        self.stop_reason: model.StopReason | None = None

    def flush_thinking(self) -> None:
        """Flush accumulated thinking content into assistant_parts."""
        if self.accumulated_thoughts:
            self.assistant_parts.append(
                message.ThinkingTextPart(
                    text="".join(self.accumulated_thoughts),
                    model_id=self.param_model,
                )
            )
            self.accumulated_thoughts.clear()
        if self.thought_signature:
            self.assistant_parts.append(
                message.ThinkingSignaturePart(
                    signature=self.thought_signature,
                    model_id=self.param_model,
                    format="google_thought_signature",
                )
            )
            self.thought_signature = None

    def flush_text(self) -> None:
        """Flush accumulated text content into assistant_parts."""
        if not self.accumulated_text:
            return
        self.assistant_parts.append(message.TextPart(text="".join(self.accumulated_text)))
        self.accumulated_text.clear()

    def get_partial_message(self) -> message.AssistantMessage | None:
        """Build a partial AssistantMessage from accumulated state.

        Flushes all accumulated content and returns the message.
        Returns None if no content has been accumulated yet.
        """
        self.flush_thinking()
        self.flush_text()

        filtered_parts: list[message.Part] = []
        for part in self.assistant_parts:
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


async def parse_google_stream(
    stream: AsyncIterator[Any],
    param: llm_param.LLMCallParameter,
    metadata_tracker: MetadataTracker,
    state: GoogleStreamStateManager,
) -> AsyncGenerator[message.LLMStreamItem]:
    stage: Literal["waiting", "thinking", "assistant", "tool"] = "waiting"

    # Track tool calls where args arrive as partial updates.
    partial_args_by_call: dict[str, dict[str, Any]] = {}
    started_tool_calls: dict[str, str] = {}  # call_id -> name
    started_tool_items: set[str] = set()
    completed_tool_items: set[str] = set()

    last_usage_metadata: UsageMetadata | None = None

    async for chunk in stream:
        log_debug(
            chunk.model_dump_json(exclude_none=True),
            style="blue",
            debug_type=DebugType.LLM_STREAM,
        )

        if state.response_id is None:
            state.response_id = getattr(chunk, "response_id", None) or uuid4().hex

        if getattr(chunk, "usage_metadata", None) is not None:
            last_usage_metadata = chunk.usage_metadata

        candidates = getattr(chunk, "candidates", None) or []
        candidate0 = candidates[0] if candidates else None
        finish_reason = getattr(candidate0, "finish_reason", None) if candidate0 else None
        if finish_reason is not None:
            if isinstance(finish_reason, str):
                reason_value = finish_reason
            else:
                reason_value = getattr(finish_reason, "name", None) or str(finish_reason)
            state.stop_reason = _map_finish_reason(reason_value)
        content = getattr(candidate0, "content", None) if candidate0 else None
        content_parts = getattr(content, "parts", None) if content else None
        if not content_parts:
            continue

        for part in content_parts:
            if getattr(part, "text", None) is not None:
                text = part.text
                if not text:
                    continue
                metadata_tracker.record_token()
                if getattr(part, "thought", False) is True:
                    if stage == "assistant":
                        state.flush_text()
                    stage = "thinking"
                    state.accumulated_thoughts.append(text)
                    if getattr(part, "thought_signature", None):
                        state.thought_signature = part.thought_signature
                    yield message.ThinkingTextDelta(content=text, response_id=state.response_id)
                else:
                    if stage == "thinking":
                        state.flush_thinking()
                    stage = "assistant"
                    state.accumulated_text.append(text)
                    yield message.AssistantTextDelta(content=text, response_id=state.response_id)

            function_call = getattr(part, "function_call", None)
            if function_call is None:
                continue

            metadata_tracker.record_token()
            call_id = getattr(function_call, "id", None) or uuid4().hex
            name = getattr(function_call, "name", None) or ""
            started_tool_calls.setdefault(call_id, name)

            if call_id not in started_tool_items:
                started_tool_items.add(call_id)
                yield message.ToolCallStartDelta(response_id=state.response_id, call_id=call_id, name=name)

            args_obj = getattr(function_call, "args", None)
            if args_obj is not None:
                if stage == "thinking":
                    state.flush_thinking()
                if stage == "assistant":
                    state.flush_text()
                stage = "tool"
                state.assistant_parts.append(
                    message.ToolCallPart(
                        call_id=call_id,
                        tool_name=name,
                        arguments_json=json.dumps(args_obj, ensure_ascii=False),
                    )
                )
                completed_tool_items.add(call_id)
                continue

            partial_args = getattr(function_call, "partial_args", None)
            if partial_args is not None:
                acc = partial_args_by_call.setdefault(call_id, {})
                _merge_partial_args(acc, partial_args)

            will_continue = getattr(function_call, "will_continue", None)
            if will_continue is False and call_id in partial_args_by_call and call_id not in completed_tool_items:
                if stage == "thinking":
                    state.flush_thinking()
                if stage == "assistant":
                    state.flush_text()
                stage = "tool"
                state.assistant_parts.append(
                    message.ToolCallPart(
                        call_id=call_id,
                        tool_name=name,
                        arguments_json=json.dumps(partial_args_by_call[call_id], ensure_ascii=False),
                    )
                )
                completed_tool_items.add(call_id)

    # Flush any pending tool calls that never produced args.
    for call_id, name in started_tool_calls.items():
        if call_id in completed_tool_items:
            continue
        args = partial_args_by_call.get(call_id, {})
        state.assistant_parts.append(
            message.ToolCallPart(
                call_id=call_id,
                tool_name=name,
                arguments_json=json.dumps(args, ensure_ascii=False),
            )
        )

    state.flush_thinking()
    state.flush_text()

    usage = _usage_from_metadata(last_usage_metadata, context_limit=param.context_limit, max_tokens=param.max_tokens)
    if usage is not None:
        metadata_tracker.set_usage(usage)
    metadata_tracker.set_model_name(str(param.model_id))
    metadata_tracker.set_response_id(state.response_id)
    metadata = metadata_tracker.finalize()
    yield message.AssistantMessage(
        parts=state.assistant_parts,
        response_id=state.response_id,
        usage=metadata,
        stop_reason=state.stop_reason,
    )


class GoogleLLMStream(LLMStreamABC):
    """LLMStream implementation for Google LLM clients."""

    def __init__(
        self,
        stream: AsyncIterator[Any],
        *,
        param: llm_param.LLMCallParameter,
        metadata_tracker: MetadataTracker,
        state: GoogleStreamStateManager,
    ) -> None:
        self._stream = stream
        self._param = param
        self._metadata_tracker = metadata_tracker
        self._state = state
        self._completed = False

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        try:
            async for item in parse_google_stream(
                self._stream,
                param=self._param,
                metadata_tracker=self._metadata_tracker,
                state=self._state,
            ):
                if isinstance(item, message.AssistantMessage):
                    self._completed = True
                yield item
        except (APIError, ClientError, ServerError, httpx.HTTPError) as e:
            yield message.StreamErrorItem(error=f"{e.__class__.__name__} {e!s}")
            yield message.AssistantMessage(parts=[], response_id=None, usage=self._metadata_tracker.finalize())

    def get_partial_message(self) -> message.AssistantMessage | None:
        if self._completed:
            return None
        return self._state.get_partial_message()


@register(llm_param.LLMClientProtocol.GOOGLE)
class GoogleClient(LLMClientABC):
    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        http_options: HttpOptions | None = None
        if config.base_url:
            # If base_url already contains version path, don't append api_version.
            http_options = HttpOptions(base_url=str(config.base_url), api_version="")

        self.client = Client(
            api_key=config.api_key,
            http_options=http_options,
        )

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        param = apply_config_defaults(param, self.get_llm_config())
        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        contents = convert_history_to_contents(param.input, model_name=str(param.model_id))
        config = _build_config(param)

        log_debug(
            json.dumps(
                {
                    "model": str(param.model_id),
                    "contents": [c.model_dump(exclude_none=True) for c in contents],
                    "config": config.model_dump(exclude_none=True),
                },
                ensure_ascii=False,
            ),
            style="yellow",
            debug_type=DebugType.LLM_PAYLOAD,
        )

        try:
            stream = await self.client.aio.models.generate_content_stream(
                model=str(param.model_id),
                contents=cast(Any, contents),
                config=config,
            )
        except (APIError, ClientError, ServerError, httpx.HTTPError) as e:
            return error_llm_stream(
                metadata_tracker,
                error=f"{e.__class__.__name__} {e!s}",
            )

        state = GoogleStreamStateManager(param_model=str(param.model_id))
        return GoogleLLMStream(
            stream,
            param=param,
            metadata_tracker=metadata_tracker,
            state=state,
        )
