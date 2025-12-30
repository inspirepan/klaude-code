# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportAttributeAccessIssue=false

import json
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast, override
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

from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.google.input import convert_history_to_contents, convert_tool_schema
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker
from klaude_code.protocol import llm_param, model
from klaude_code.trace import DebugType, log_debug


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
        tools=tool_list or None,
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


async def parse_google_stream(
    stream: AsyncIterator[Any],
    param: llm_param.LLMCallParameter,
    metadata_tracker: MetadataTracker,
) -> AsyncGenerator[model.ConversationItem]:
    response_id: str | None = None
    started = False

    accumulated_text: list[str] = []
    accumulated_thoughts: list[str] = []
    thought_signature: str | None = None

    # Track tool calls where args arrive as partial updates.
    partial_args_by_call: dict[str, dict[str, Any]] = {}
    started_tool_calls: dict[str, str] = {}  # call_id -> name
    started_tool_items: set[str] = set()
    emitted_tool_items: set[str] = set()

    last_usage_metadata: UsageMetadata | None = None

    async for chunk in stream:
        log_debug(
            chunk.model_dump_json(exclude_none=True),
            style="blue",
            debug_type=DebugType.LLM_STREAM,
        )

        if response_id is None:
            response_id = getattr(chunk, "response_id", None) or uuid4().hex
        assert response_id is not None
        if not started:
            started = True
            yield model.StartItem(response_id=response_id)

        if getattr(chunk, "usage_metadata", None) is not None:
            last_usage_metadata = chunk.usage_metadata

        candidates = getattr(chunk, "candidates", None) or []
        candidate0 = candidates[0] if candidates else None
        content = getattr(candidate0, "content", None) if candidate0 else None
        parts = getattr(content, "parts", None) if content else None
        if not parts:
            continue

        for part in parts:
            if getattr(part, "text", None) is not None:
                metadata_tracker.record_token()
                text = part.text
                if getattr(part, "thought", False) is True:
                    accumulated_thoughts.append(text)
                    if getattr(part, "thought_signature", None):
                        thought_signature = part.thought_signature
                    yield model.ReasoningTextDelta(content=text, response_id=response_id)
                else:
                    accumulated_text.append(text)
                    yield model.AssistantMessageDelta(content=text, response_id=response_id)

            function_call = getattr(part, "function_call", None)
            if function_call is None:
                continue

            metadata_tracker.record_token()
            call_id = getattr(function_call, "id", None) or uuid4().hex
            name = getattr(function_call, "name", None) or ""
            started_tool_calls.setdefault(call_id, name)

            if call_id not in started_tool_items:
                started_tool_items.add(call_id)
                yield model.ToolCallStartItem(response_id=response_id, call_id=call_id, name=name)

            args_obj = getattr(function_call, "args", None)
            if args_obj is not None:
                emitted_tool_items.add(call_id)
                yield model.ToolCallItem(
                    response_id=response_id,
                    call_id=call_id,
                    name=name,
                    arguments=json.dumps(args_obj, ensure_ascii=False),
                )
                continue

            partial_args = getattr(function_call, "partial_args", None)
            if partial_args is not None:
                acc = partial_args_by_call.setdefault(call_id, {})
                _merge_partial_args(acc, partial_args)

            will_continue = getattr(function_call, "will_continue", None)
            if will_continue is False and call_id in partial_args_by_call and call_id not in emitted_tool_items:
                emitted_tool_items.add(call_id)
                yield model.ToolCallItem(
                    response_id=response_id,
                    call_id=call_id,
                    name=name,
                    arguments=json.dumps(partial_args_by_call[call_id], ensure_ascii=False),
                )

    # Flush any pending tool calls that never produced args.
    for call_id, name in started_tool_calls.items():
        if call_id in emitted_tool_items:
            continue
        args = partial_args_by_call.get(call_id, {})
        emitted_tool_items.add(call_id)
        yield model.ToolCallItem(
            response_id=response_id,
            call_id=call_id,
            name=name,
            arguments=json.dumps(args, ensure_ascii=False),
        )

    if accumulated_thoughts:
        metadata_tracker.record_token()
        yield model.ReasoningTextItem(
            content="".join(accumulated_thoughts),
            response_id=response_id,
            model=str(param.model),
        )
        if thought_signature:
            yield model.ReasoningEncryptedItem(
                encrypted_content=thought_signature,
                response_id=response_id,
                model=str(param.model),
                format="google_thought_signature",
            )

    if accumulated_text:
        metadata_tracker.record_token()
        yield model.AssistantMessageItem(content="".join(accumulated_text), response_id=response_id)

    usage = _usage_from_metadata(last_usage_metadata, context_limit=param.context_limit, max_tokens=param.max_tokens)
    if usage is not None:
        metadata_tracker.set_usage(usage)
    metadata_tracker.set_model_name(str(param.model))
    metadata_tracker.set_response_id(response_id)
    yield metadata_tracker.finalize()


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
    async def call(self, param: llm_param.LLMCallParameter) -> AsyncGenerator[model.ConversationItem]:
        param = apply_config_defaults(param, self.get_llm_config())
        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        contents = convert_history_to_contents(param.input, model_name=str(param.model))
        config = _build_config(param)

        log_debug(
            json.dumps(
                {
                    "model": str(param.model),
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
                model=str(param.model),
                contents=cast(Any, contents),
                config=config,
            )
        except (APIError, ClientError, ServerError, httpx.HTTPError) as e:
            yield model.StreamErrorItem(error=f"{e.__class__.__name__} {e!s}")
            yield metadata_tracker.finalize()
            return

        try:
            async for item in parse_google_stream(stream, param=param, metadata_tracker=metadata_tracker):
                yield item
        except (APIError, ClientError, ServerError, httpx.HTTPError) as e:
            yield model.StreamErrorItem(error=f"{e.__class__.__name__} {e!s}")
            yield metadata_tracker.finalize()
