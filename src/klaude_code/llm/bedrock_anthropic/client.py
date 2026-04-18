"""AWS Bedrock LLM client using native ConverseStream."""

import asyncio
import base64
import json
from collections.abc import AsyncGenerator
from importlib.util import find_spec
from typing import Any, cast, override

try:
    import botocore.exceptions as _botocore_exceptions  # pyright: ignore[reportMissingTypeStubs]
except ModuleNotFoundError:
    _botocore_exceptions = None

import httpx

from klaude_code.const import (
    ANTHROPIC_BETA_CONTEXT_MANAGEMENT,
    ANTHROPIC_BETA_INTERLEAVED_THINKING,
    CLAUDE_CODE_IDENTITY,
    DEFAULT_ANTHROPIC_THINKING_BUDGET_TOKENS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    LLM_HTTP_TIMEOUT_CONNECT,
    LLM_HTTP_TIMEOUT_READ,
)
from klaude_code.llm.anthropic.client import AnthropicStreamStateManager
from klaude_code.llm.anthropic.input import convert_history_to_input, convert_system_to_input
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.image import detect_mime_type_from_bytes, parse_data_url
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import llm_param, message, model
from klaude_code.protocol.model_id import is_opus_47_model, supports_adaptive_thinking

_BotocoreBotoCoreErrorType = cast(
    type[Exception],
    _botocore_exceptions.BotoCoreError if _botocore_exceptions is not None else Exception,
)
_BotocoreClientErrorType = cast(
    type[Exception],
    _botocore_exceptions.ClientError if _botocore_exceptions is not None else Exception,
)
_BotocoreEventStreamErrorType = cast(
    type[Exception],
    _botocore_exceptions.EventStreamError if _botocore_exceptions is not None else Exception,
)


class BedrockRequestError(Exception):
    pass


class BedrockStreamError(Exception):
    pass


def _map_bedrock_stop_reason(reason: str | None) -> model.StopReason | None:
    mapping: dict[str, model.StopReason] = {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "model_context_window_exceeded": "length",
        "tool_use": "tool_use",
        "content_filtered": "error",
        "guardrail_intervened": "error",
        "malformed_model_output": "error",
        "malformed_tool_use": "error",
    }
    return mapping.get(reason or "")


def _is_govcloud_target(model_id: str, region: str | None) -> bool:
    region_lower = (region or "").lower()
    model_lower = model_id.lower()
    return (
        region_lower.startswith("us-gov-")
        or model_lower.startswith("us-gov.")
        or model_lower.startswith("arn:aws-us-gov:")
    )


def _image_format_for_mime_type(mime_type: str) -> str:
    formats = {
        "image/png": "png",
        "image/jpeg": "jpeg",
        "image/jpg": "jpeg",
        "image/gif": "gif",
        "image/webp": "webp",
    }
    if mime_type.lower() not in formats:
        raise BedrockRequestError(f"Unsupported Bedrock image MIME type: {mime_type}")
    return formats[mime_type.lower()]


def _convert_image_source(source: dict[str, Any]) -> dict[str, Any]:
    source_type = source.get("type")
    if source_type == "base64":
        media_type = cast(str, source["media_type"])
        data = base64.b64decode(cast(str, source["data"]))
        return {
            "format": _image_format_for_mime_type(media_type),
            "source": {"bytes": data},
        }

    if source_type == "url":
        url = cast(str, source["url"])
        if url.startswith("data:"):
            media_type, _, data = parse_data_url(url)
        else:
            response = httpx.get(
                url,
                follow_redirects=True,
                timeout=httpx.Timeout(LLM_HTTP_TIMEOUT_READ, connect=LLM_HTTP_TIMEOUT_CONNECT),
            )
            response.raise_for_status()
            data = response.content
            header_mime = response.headers.get("content-type", "").split(";", 1)[0].strip()
            media_type = header_mime or detect_mime_type_from_bytes(data) or "application/octet-stream"
        return {
            "format": _image_format_for_mime_type(media_type),
            "source": {"bytes": data},
        }

    raise BedrockRequestError(f"Unsupported Bedrock image source type: {source_type}")


def _append_cache_point(target: list[dict[str, Any]], source_block: dict[str, Any]) -> None:
    if source_block.get("cache_control"):
        target.append({"cachePoint": {"type": "default"}})


def _convert_content_block(block: dict[str, Any], *, model_id: str) -> list[dict[str, Any]]:
    block_type = block.get("type")
    result: list[dict[str, Any]] = []

    if block_type == "text":
        result.append({"text": block.get("text", "")})
        _append_cache_point(result, block)
        return result

    if block_type == "image":
        image = _convert_image_source(cast(dict[str, Any], block["source"]))
        result.append({"image": image})
        _append_cache_point(result, block)
        return result

    if block_type == "tool_result":
        tool_content: list[dict[str, Any]] = []
        for item in cast(list[dict[str, Any]], block.get("content", [])):
            tool_content.extend(_convert_content_block(item, model_id=model_id))
        result.append(
            {
                "toolResult": {
                    "toolUseId": block["tool_use_id"],
                    "status": "error" if block.get("is_error") else "success",
                    "content": tool_content,
                }
            }
        )
        _append_cache_point(result, block)
        return result

    if block_type == "tool_use":
        result.append(
            {
                "toolUse": {
                    "toolUseId": block["id"],
                    "name": block["name"],
                    "input": block.get("input", {}),
                }
            }
        )
        _append_cache_point(result, block)
        return result

    if block_type == "thinking":
        thinking_text = cast(str, block.get("thinking") or "")
        if not thinking_text.strip():
            return result
        signature = cast(str | None, block.get("signature"))
        if signature:
            result.append(
                {
                    "reasoningContent": {
                        "reasoningText": {
                            "text": thinking_text,
                            "signature": signature,
                        }
                    }
                }
            )
        elif "claude" in model_id.lower():
            result.append({"text": thinking_text})
        else:
            result.append({"reasoningContent": {"reasoningText": {"text": thinking_text}}})
        _append_cache_point(result, block)
        return result

    raise BedrockRequestError(f"Unsupported Bedrock content block type: {block_type}")


def _is_claude_bedrock_target(model_id: str) -> bool:
    model_lower = model_id.lower()
    return (
        "claude" in model_lower
        or model_lower.startswith("arn:aws:bedrock:")
        or model_lower.startswith("arn:aws-us-gov:")
    )


def _convert_messages(param: llm_param.LLMCallParameter) -> list[dict[str, Any]]:
    model_id = str(param.model_id)
    anthropic_messages = convert_history_to_input(param.input, model_id)
    result: list[dict[str, Any]] = []

    for msg in anthropic_messages:
        content: list[dict[str, Any]] = []
        for block in cast(list[dict[str, Any]], msg.get("content", [])):
            content.extend(_convert_content_block(block, model_id=model_id))
        if not content:
            content = [{"text": ""}]
        result.append({"role": msg["role"], "content": content})

    return result


def _convert_system(param: llm_param.LLMCallParameter) -> list[dict[str, Any]]:
    system_messages = [msg for msg in param.input if isinstance(msg, message.SystemMessage)]
    system_blocks = convert_system_to_input(param.system, system_messages)
    result: list[dict[str, Any]] = []

    result.append({"text": CLAUDE_CODE_IDENTITY})
    result.append({"cachePoint": {"type": "default"}})

    for block in system_blocks:
        result.append({"text": block["text"]})
        if block.get("cache_control"):
            result.append({"cachePoint": {"type": "default"}})

    return result


def _convert_tool_config(tools: list[llm_param.ToolSchema] | None) -> dict[str, Any] | None:
    if not tools:
        return None

    return {
        "tools": [
            {
                "toolSpec": {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": {"json": tool.parameters},
                }
            }
            for tool in tools
        ],
        "toolChoice": {"auto": {}},
    }


def _build_additional_model_request_fields(
    param: llm_param.LLMCallParameter,
    *,
    model_id: str,
    region: str | None,
) -> dict[str, Any] | None:
    result: dict[str, Any] = {}
    anthropic_betas: list[str] = []

    if param.thinking and param.thinking.type in {"adaptive", "enabled"} and _is_claude_bedrock_target(model_id):
        display = None if _is_govcloud_target(model_id, region) else "summarized"
        if param.thinking.type == "adaptive":
            thinking: dict[str, Any] = {"type": "adaptive"}
        else:
            thinking = {
                "type": "enabled",
                "budget_tokens": param.thinking.budget_tokens or DEFAULT_ANTHROPIC_THINKING_BUDGET_TOKENS,
            }
        if display is not None:
            thinking["display"] = display
        result["thinking"] = thinking
        result["context_management"] = {
            "edits": [{"type": "clear_thinking_20251015", "keep": "all"}],
        }
        anthropic_betas.append(ANTHROPIC_BETA_CONTEXT_MANAGEMENT)

        if param.thinking.type == "enabled" and not supports_adaptive_thinking(model_id):
            anthropic_betas.append(ANTHROPIC_BETA_INTERLEAVED_THINKING)

    if anthropic_betas:
        result["anthropic_beta"] = anthropic_betas

    if param.effort:
        result["output_config"] = {"effort": param.effort}

    return result or None


def build_bedrock_request(
    param: llm_param.LLMCallParameter,
    *,
    region: str | None,
) -> dict[str, Any]:
    model_id = str(param.model_id)
    inference_config: dict[str, Any] = {
        "maxTokens": param.max_tokens or DEFAULT_MAX_TOKENS,
    }
    if not is_opus_47_model(model_id):
        inference_config["temperature"] = param.temperature or DEFAULT_TEMPERATURE

    request: dict[str, Any] = {
        "modelId": model_id,
        "messages": _convert_messages(param),
        "inferenceConfig": inference_config,
    }

    system = _convert_system(param)
    if system:
        request["system"] = system

    tool_config = _convert_tool_config(param.tools)
    if tool_config:
        request["toolConfig"] = tool_config

    additional = _build_additional_model_request_fields(param, model_id=model_id, region=region)
    if additional:
        request["additionalModelRequestFields"] = additional

    return request


def _next_stream_event(iterator: Any) -> tuple[bool, dict[str, Any] | None]:
    try:
        return False, cast(dict[str, Any], next(iterator))
    except StopIteration:
        return True, None


def _format_bedrock_stream_error(event: dict[str, Any]) -> str:
    for key in (
        "internalServerException",
        "modelStreamErrorException",
        "validationException",
        "throttlingException",
        "serviceUnavailableException",
    ):
        value = event.get(key)
        if value:
            if isinstance(value, dict):
                value_dict = cast(dict[str, Any], value)
                error_message = cast(str | None, value_dict.get("message"))
                if error_message:
                    return f"{key}: {error_message}"
            return f"{key}: {value}"
    return json.dumps(event, ensure_ascii=False, default=str)


async def parse_bedrock_stream(
    response: dict[str, Any],
    param: llm_param.LLMCallParameter,
    metadata_tracker: MetadataTracker,
    state: AnthropicStreamStateManager,
) -> AsyncGenerator[message.LLMStreamItem]:
    response_metadata = cast(dict[str, Any], response.get("ResponseMetadata") or {})
    request_id = cast(str | None, response_metadata.get("RequestId"))
    if request_id:
        state.response_id = request_id

    stream: Any = response.get("stream")
    if stream is None:
        raise BedrockStreamError("Bedrock ConverseStream returned no stream")

    iterator = iter(stream)
    while True:
        done, event = await asyncio.to_thread(_next_stream_event, iterator)
        if done:
            break
        if event is None:
            continue

        log_debug(json.dumps(event, ensure_ascii=False, default=str), debug_type=DebugType.LLM_STREAM)

        if "messageStart" in event:
            continue

        if "contentBlockStart" in event:
            start = cast(dict[str, Any], event["contentBlockStart"].get("start") or {})
            tool_use = cast(dict[str, Any] | None, start.get("toolUse"))
            if tool_use:
                metadata_tracker.record_token()
                call_id = cast(str, tool_use.get("toolUseId") or "")
                tool_name = cast(str, tool_use.get("name") or "")
                state.flush_pending_signature()
                state.current_tool_name = tool_name
                state.current_tool_call_id = call_id
                state.current_tool_inputs = []
                yield message.ToolCallStartDelta(response_id=state.response_id, call_id=call_id, name=tool_name)
            continue

        if "contentBlockDelta" in event:
            delta = cast(dict[str, Any], event["contentBlockDelta"].get("delta") or {})
            reasoning = cast(dict[str, Any] | None, delta.get("reasoningContent"))
            if reasoning:
                thinking_text = cast(str | None, reasoning.get("text"))
                if thinking_text:
                    metadata_tracker.record_token()
                    state.append_thinking_text(thinking_text)
                    yield message.ThinkingTextDelta(content=thinking_text, response_id=state.response_id)
                signature = cast(str | None, reasoning.get("signature"))
                if signature:
                    state.set_pending_signature(signature)
                continue

            text = cast(str | None, delta.get("text"))
            if text:
                metadata_tracker.record_token()
                state.flush_pending_signature()
                state.append_text(text)
                yield message.AssistantTextDelta(content=text, response_id=state.response_id)
                continue

            tool_use_delta = cast(dict[str, Any] | None, delta.get("toolUse"))
            if tool_use_delta and state.current_tool_inputs is not None:
                partial_json = cast(str | None, tool_use_delta.get("input"))
                if partial_json:
                    metadata_tracker.record_token()
                    state.current_tool_inputs.append(partial_json)
            continue

        if "contentBlockStop" in event:
            state.flush_pending_signature()
            if state.current_tool_name and state.current_tool_call_id:
                metadata_tracker.record_token()
                state.flush_tool_call()
            continue

        if "messageStop" in event:
            stop_reason = cast(str | None, event["messageStop"].get("stopReason"))
            state.stop_reason = _map_bedrock_stop_reason(stop_reason)
            continue

        if "metadata" in event:
            usage = cast(dict[str, Any], event["metadata"].get("usage") or {})
            input_tokens = cast(int, usage.get("inputTokens") or 0)
            output_tokens = cast(int, usage.get("outputTokens") or 0)
            cached_tokens = cast(int, usage.get("cacheReadInputTokens") or 0)
            cache_write_tokens = cast(int, usage.get("cacheWriteInputTokens") or 0)
            metadata_tracker.set_usage(
                model.Usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_tokens=cached_tokens,
                    cache_write_tokens=cache_write_tokens,
                    context_size=cast(int | None, usage.get("totalTokens")),
                    context_limit=param.context_limit,
                    max_tokens=param.max_tokens,
                )
            )
            continue

        raise BedrockStreamError(_format_bedrock_stream_error(event))

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


class BedrockLLMStream(LLMStreamABC):
    def __init__(
        self,
        response: dict[str, Any],
        *,
        param: llm_param.LLMCallParameter,
        metadata_tracker: MetadataTracker,
    ) -> None:
        self._response = response
        self._param = param
        self._metadata_tracker = metadata_tracker
        self._state = AnthropicStreamStateManager(model_id=str(param.model_id))
        self._completed = False

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        try:
            async for item in parse_bedrock_stream(
                self._response,
                self._param,
                self._metadata_tracker,
                self._state,
            ):
                if isinstance(item, message.AssistantMessage):
                    self._completed = True
                yield item
        except (BedrockStreamError, _BotocoreBotoCoreErrorType, _BotocoreEventStreamErrorType, httpx.HTTPError) as e:
            yield message.StreamErrorItem(error=f"{e.__class__.__name__} {e!s}")
            self._metadata_tracker.set_model_name(str(self._param.model_id))
            self._metadata_tracker.set_response_id(self._state.response_id)
            metadata = self._metadata_tracker.finalize()
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


@register(llm_param.LLMClientProtocol.BEDROCK)
class BedrockClient(LLMClientABC):
    """LLM client for AWS Bedrock using native ConverseStream."""

    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        missing = [name for name in ("boto3", "botocore") if find_spec(name) is None]
        if missing:
            missing_names = ", ".join(missing)
            raise ModuleNotFoundError(
                "Bedrock support requires boto3 and botocore. "
                f"Missing: {missing_names}. Reinstall klaude-code with `anthropic[bedrock]`."
            )

        import boto3  # pyright: ignore[reportMissingTypeStubs]
        from botocore.config import Config  # pyright: ignore[reportMissingTypeStubs]

        session_kwargs: dict[str, Any] = {}
        if config.aws_access_key:
            session_kwargs["aws_access_key_id"] = config.aws_access_key
        if config.aws_secret_key:
            session_kwargs["aws_secret_access_key"] = config.aws_secret_key
        if config.aws_session_token:
            session_kwargs["aws_session_token"] = config.aws_session_token
        if config.aws_region:
            session_kwargs["region_name"] = config.aws_region
        if config.aws_profile:
            session_kwargs["profile_name"] = config.aws_profile

        session: Any = boto3.Session(**session_kwargs)
        self.client: Any = session.client(
            "bedrock-runtime",
            region_name=config.aws_region,
            config=Config(
                connect_timeout=LLM_HTTP_TIMEOUT_CONNECT,
                read_timeout=LLM_HTTP_TIMEOUT_READ,
            ),
        )

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)
        request = await asyncio.to_thread(build_bedrock_request, param, region=self.get_llm_config().aws_region)

        log_debug(
            json.dumps(request, ensure_ascii=False, default=str),
            debug_type=DebugType.LLM_PAYLOAD,
        )

        try:
            response = cast(dict[str, Any], await asyncio.to_thread(self.client.converse_stream, **request))
            return BedrockLLMStream(response, param=param, metadata_tracker=metadata_tracker)
        except (
            BedrockRequestError,
            _BotocoreBotoCoreErrorType,
            _BotocoreClientErrorType,
            _BotocoreEventStreamErrorType,
            httpx.HTTPError,
        ) as e:
            error_message = f"{e.__class__.__name__} {e!s}"
            return error_llm_stream(metadata_tracker, error=error_message)
