# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportAttributeAccessIssue=false

from base64 import b64encode
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast, override
from uuid import uuid4

import httpx
from google.genai import Client
from google.genai.errors import APIError, ClientError, ServerError
from google.genai.types import (
    ContentListUnion,
    FunctionCallingConfig,
    FunctionCallingConfigMode,
    GenerateContentConfig,
    GenerateContentResponse,
    GenerateContentResponseUsageMetadata,
    HttpOptions,
    PartialArg,
    ThinkingConfig,
    ThinkingLevel,
    ToolConfig,
)
from google.genai.types import (
    ImageConfig as GoogleImageConfig,
)

from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.google.input import convert_history_to_contents, convert_tool_schema
from klaude_code.llm.image import save_assistant_image
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.json_stable import dumps_canonical_json
from klaude_code.llm.registry import register
from klaude_code.llm.stream_parts import (
    append_text_part,
    append_thinking_text_part,
    build_partial_message,
    build_partial_parts,
)
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.log import DebugType, debug_json, log_debug
from klaude_code.protocol import llm_param, message, model

# Unified format for Google thought signatures
GOOGLE_THOUGHT_SIGNATURE_FORMAT = "google"

# Synthetic signature for image parts that need one but don't have it.
# See: https://ai.google.dev/gemini-api/docs/thought-signatures
SYNTHETIC_THOUGHT_SIGNATURE = b"skip_thought_signature_validator"


def support_thinking(model_id: str | None) -> bool:
    return bool(model_id) and ("gemini-3" in model_id or "gemini-2.5-pro" in model_id)


def convert_gemini_thinking_level(reasoning_effort: str | None) -> ThinkingLevel | None:
    """Convert reasoning_effort to Gemini ThinkingLevel."""
    if reasoning_effort is None:
        return None
    mapping: dict[str, ThinkingLevel] = {
        "xhigh": ThinkingLevel.HIGH,
        "high": ThinkingLevel.HIGH,
        "medium": ThinkingLevel.MEDIUM,
        "low": ThinkingLevel.LOW,
        "minimal": ThinkingLevel.MINIMAL,
        "none": ThinkingLevel.MINIMAL,
    }
    return mapping.get(reasoning_effort)


def _build_config(param: llm_param.LLMCallParameter) -> GenerateContentConfig:
    tool_list = convert_tool_schema(param.tools)
    tool_config: ToolConfig | None = None

    if tool_list:
        tool_config = ToolConfig(
            function_calling_config=FunctionCallingConfig(
                mode=FunctionCallingConfigMode.AUTO,
            )
        )

    thinking_config: ThinkingConfig | None = None
    if support_thinking(param.model_id):
        thinking_config: ThinkingConfig | None = ThinkingConfig(
            include_thoughts=True,
        )

        if param.thinking:
            if param.thinking.budget_tokens:
                thinking_config.thinking_budget = param.thinking.budget_tokens
            if param.thinking.reasoning_effort:
                thinking_config.thinking_level = convert_gemini_thinking_level(param.thinking.reasoning_effort)

    # ImageGen per-call overrides
    image_config: GoogleImageConfig | None = None
    if param.image_config is not None:
        image_config = GoogleImageConfig(
            aspect_ratio=param.image_config.aspect_ratio,
            image_size=param.image_config.image_size,
        )

    return GenerateContentConfig(
        system_instruction=param.system,
        temperature=param.temperature,
        max_output_tokens=param.max_tokens,
        tools=cast(Any, tool_list) if tool_list else None,
        tool_config=tool_config,
        thinking_config=thinking_config,
        image_config=image_config,
    )


def _usage_from_metadata(
    usage: GenerateContentResponseUsageMetadata | None,
    *,
    context_limit: int | None,
    max_tokens: int | None,
) -> model.Usage | None:
    if usage is None:
        return None

    # In Gemini usage metadata, prompt_token_count represents the full prompt tokens
    # (including cached tokens). cached_content_token_count is a subset of prompt tokens.
    cached = usage.cached_content_token_count or 0
    prompt = usage.prompt_token_count or 0
    response = usage.candidates_token_count or 0
    thoughts = usage.thoughts_token_count or 0

    # Extract image tokens from candidates_tokens_details
    image_tokens = 0
    if usage.candidates_tokens_details:
        for detail in usage.candidates_tokens_details:
            if detail.modality and detail.modality.name == "IMAGE" and detail.token_count:
                image_tokens += detail.token_count

    total = usage.total_token_count
    if total is None:
        total = prompt + response + thoughts

    return model.Usage(
        input_tokens=prompt,
        cached_tokens=cached,
        output_tokens=response + thoughts,
        reasoning_tokens=thoughts,
        image_tokens=image_tokens,
        context_size=total,
        context_limit=context_limit,
        max_tokens=max_tokens,
    )


def _partial_arg_value(partial: PartialArg) -> str | float | bool | None:
    if partial.string_value is not None:
        return partial.string_value
    if partial.number_value is not None:
        return partial.number_value
    if partial.bool_value is not None:
        return partial.bool_value
    return None


def _merge_partial_args(dst: dict[str, Any], partial_args: list[PartialArg] | None) -> None:
    if not partial_args:
        return
    for partial in partial_args:
        json_path = partial.json_path
        if not json_path or not json_path.startswith("$."):
            continue
        key = json_path[2:]
        if not key or any(ch in key for ch in "[]"):
            continue
        dst[key] = _partial_arg_value(partial)


def _encode_thought_signature(sig: bytes | str | None) -> str | None:
    """Encode thought signature bytes to base64 string."""
    if sig is None:
        return None
    if isinstance(sig, bytes):
        return b64encode(sig).decode("ascii")
    return sig


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

    Accumulates parts directly during streaming to support get_partial_message()
    for cancellation scenarios. Merges consecutive text parts of the same type.
    """

    def __init__(self, param_model: str) -> None:
        self.param_model = param_model
        self.assistant_parts: list[message.Part] = []
        self.response_id: str | None = None
        self.stop_reason: model.StopReason | None = None

    def append_thinking_text(self, text: str) -> None:
        """Append thinking text, merging with previous ThinkingTextPart if possible."""
        append_thinking_text_part(self.assistant_parts, text, model_id=self.param_model)

    def append_text(self, text: str) -> None:
        """Append text, merging with previous TextPart if possible."""
        append_text_part(self.assistant_parts, text)

    def append_thinking_signature(self, signature: str) -> None:
        """Append a ThinkingSignaturePart after the current part."""
        self.assistant_parts.append(
            message.ThinkingSignaturePart(
                signature=signature,
                model_id=self.param_model,
                format=GOOGLE_THOUGHT_SIGNATURE_FORMAT,
            )
        )

    def append_image(self, image_part: message.ImageFilePart) -> None:
        """Append an ImageFilePart."""
        self.assistant_parts.append(image_part)

    def append_tool_call(self, call_id: str, name: str, arguments_json: str) -> None:
        """Append a ToolCallPart."""
        self.assistant_parts.append(
            message.ToolCallPart(
                call_id=call_id,
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


async def parse_google_stream(
    stream: AsyncIterator[GenerateContentResponse],
    param: llm_param.LLMCallParameter,
    metadata_tracker: MetadataTracker,
    state: GoogleStreamStateManager,
) -> AsyncGenerator[message.LLMStreamItem]:
    # Track tool calls where args arrive as partial updates.
    partial_args_by_call: dict[str, dict[str, Any]] = {}
    started_tool_calls: dict[str, tuple[str, bytes | None]] = {}  # call_id -> (name, thought_signature)
    started_tool_items: set[str] = set()
    completed_tool_items: set[str] = set()

    # Track image index for unique filenames
    image_index = 0

    last_usage_metadata: GenerateContentResponseUsageMetadata | None = None

    async for chunk in stream:
        log_debug(debug_json(chunk.model_dump(exclude_none=True)), style="blue", debug_type=DebugType.LLM_STREAM)

        if state.response_id is None:
            state.response_id = chunk.response_id or uuid4().hex

        if chunk.usage_metadata is not None:
            last_usage_metadata = chunk.usage_metadata

        candidates = chunk.candidates or []
        candidate0 = candidates[0] if candidates else None
        finish_reason = candidate0.finish_reason if candidate0 else None
        if finish_reason is not None:
            state.stop_reason = _map_finish_reason(finish_reason.name)
        content = candidate0.content if candidate0 else None
        content_parts = content.parts if content else None
        if not content_parts:
            continue

        for part in content_parts:
            # Handle text parts (both thought and regular text)
            if part.text is not None:
                text = part.text
                if not text:
                    continue
                metadata_tracker.record_token()

                if part.thought is True:
                    # Thinking text - append and merge with previous ThinkingTextPart
                    state.append_thinking_text(text)
                    # Add ThinkingSignaturePart after thinking text if present
                    if part.thought_signature:
                        encoded_sig = _encode_thought_signature(part.thought_signature)
                        if encoded_sig:
                            state.append_thinking_signature(encoded_sig)
                    yield message.ThinkingTextDelta(content=text, response_id=state.response_id)
                else:
                    # Regular text - append and merge with previous TextPart
                    state.append_text(text)
                    # Regular text parts can also have thought_signature
                    if part.thought_signature:
                        encoded_sig = _encode_thought_signature(part.thought_signature)
                        if encoded_sig:
                            state.append_thinking_signature(encoded_sig)
                    yield message.AssistantTextDelta(content=text, response_id=state.response_id)

            # Handle inline_data (image generation responses)
            inline_data = part.inline_data
            if inline_data is not None and inline_data.data:
                # Thought images (interim images produced during thinking) do not
                # carry thought signatures and must not be treated as response
                # images for multi-turn history.
                if part.thought is True:
                    continue
                mime_type = inline_data.mime_type or "image/png"
                encoded_data = b64encode(inline_data.data).decode("ascii")
                data_url = f"data:{mime_type};base64,{encoded_data}"
                try:
                    image_part = save_assistant_image(
                        data_url=data_url,
                        session_id=param.session_id,
                        response_id=state.response_id,
                        image_index=image_index,
                    )
                    image_index += 1
                    state.append_image(image_part)
                    # Add ThinkingSignaturePart after image if present, or synthetic signature for thinking models
                    if part.thought_signature:
                        encoded_sig = _encode_thought_signature(part.thought_signature)
                        if encoded_sig:
                            state.append_thinking_signature(encoded_sig)
                    elif support_thinking(param.model_id):
                        encoded_sig = _encode_thought_signature(SYNTHETIC_THOUGHT_SIGNATURE)
                        if encoded_sig:
                            state.append_thinking_signature(encoded_sig)
                    yield message.AssistantImageDelta(
                        response_id=state.response_id,
                        file_path=image_part.file_path,
                    )
                except ValueError:
                    pass  # Skip invalid images

            # Handle function calls
            function_call = part.function_call
            if function_call is None:
                continue

            metadata_tracker.record_token()
            call_id = function_call.id or uuid4().hex
            name = function_call.name or ""

            # Capture thought_signature from the part (required for tools in thinking models)
            thought_signature = part.thought_signature

            # Store name and thought_signature for later use (partial args / flush)
            if call_id not in started_tool_calls or (thought_signature and started_tool_calls[call_id][1] is None):
                started_tool_calls[call_id] = (name, thought_signature)

            if call_id not in started_tool_items:
                started_tool_items.add(call_id)
                yield message.ToolCallStartDelta(response_id=state.response_id, call_id=call_id, name=name)

            args_obj = function_call.args
            if args_obj is not None:
                # Add ToolCallPart, then ThinkingSignaturePart after it
                state.append_tool_call(call_id, name, dumps_canonical_json(args_obj))
                encoded_sig = _encode_thought_signature(thought_signature)
                if encoded_sig:
                    state.append_thinking_signature(encoded_sig)
                completed_tool_items.add(call_id)
                continue

            partial_args = function_call.partial_args
            if partial_args is not None:
                acc = partial_args_by_call.setdefault(call_id, {})
                _merge_partial_args(acc, partial_args)

            will_continue = function_call.will_continue
            if will_continue is False and call_id in partial_args_by_call and call_id not in completed_tool_items:
                # Add ToolCallPart, then ThinkingSignaturePart after it
                state.append_tool_call(call_id, name, dumps_canonical_json(partial_args_by_call[call_id]))
                stored_sig = started_tool_calls.get(call_id, (name, None))[1]
                encoded_stored_sig = _encode_thought_signature(stored_sig)
                if encoded_stored_sig:
                    state.append_thinking_signature(encoded_stored_sig)
                completed_tool_items.add(call_id)

    # Flush any pending tool calls that never produced args.
    for call_id, (name, stored_sig) in started_tool_calls.items():
        if call_id in completed_tool_items:
            continue
        args = partial_args_by_call.get(call_id, {})
        state.append_tool_call(call_id, name, dumps_canonical_json(args))
        encoded_stored_sig = _encode_thought_signature(stored_sig)
        if encoded_stored_sig:
            state.append_thinking_signature(encoded_stored_sig)

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
        stream: AsyncIterator[GenerateContentResponse],
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
            # Use accumulated parts for potential prefill on retry
            self._metadata_tracker.set_response_id(self._state.response_id)
            yield message.AssistantMessage(
                parts=self._state.get_partial_parts(),
                response_id=self._state.response_id,
                usage=self._metadata_tracker.finalize(),
                stop_reason="error",
            )

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
            debug_json(
                {
                    "model": str(param.model_id),
                    "contents": [c.model_dump(exclude_none=True) for c in contents],
                    "config": config.model_dump(exclude_none=True),
                }
            ),
            style="yellow",
            debug_type=DebugType.LLM_PAYLOAD,
        )

        try:
            stream = await self.client.aio.models.generate_content_stream(
                model=str(param.model_id),
                contents=cast(ContentListUnion, contents),
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
