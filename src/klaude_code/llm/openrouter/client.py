import json
from typing import Any, cast, override

import httpx
import openai
from openai.types.chat.completion_create_params import CompletionCreateParamsStreaming

from klaude_code.const import (
    ANTHROPIC_BETA_FINE_GRAINED_TOOL_STREAMING,
    ANTHROPIC_BETA_INTERLEAVED_THINKING,
    LLM_HTTP_TIMEOUT_CONNECT,
    LLM_HTTP_TIMEOUT_READ,
    LLM_HTTP_TIMEOUT_TOTAL,
    OPENROUTER_BASE_URL,
)
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.openai_compatible.input import convert_tool_schema
from klaude_code.llm.openai_compatible.stream import OpenAILLMStream
from klaude_code.llm.openrouter.input import convert_history_to_input, is_claude_model
from klaude_code.llm.openrouter.reasoning import ReasoningStreamHandler
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.log import DebugType, is_debug_enabled, log_debug
from klaude_code.protocol import llm_param


def build_payload(
    param: llm_param.LLMCallParameter,
) -> tuple[CompletionCreateParamsStreaming, dict[str, object], dict[str, str]]:
    """Build OpenRouter API request parameters."""
    messages = convert_history_to_input(param.input, param.system, param.model_id)
    tools = convert_tool_schema(param.tools)

    extra_body: dict[str, object] = {
        "usage": {"include": True},  # To get the cache tokens at the end of the response
    }

    if param.modalities:
        extra_body["modalities"] = list(param.modalities)
    if param.image_config is not None:
        image_config = param.image_config.model_dump(exclude_none=True)
        extra_raw = image_config.pop("extra", None)
        extra_dict: dict[str, Any] | None = cast(dict[str, Any], extra_raw) if isinstance(extra_raw, dict) else None
        if extra_dict is not None and extra_dict:
            image_config.update(extra_dict)
        extra_body["image_config"] = image_config
    if is_debug_enabled():
        extra_body["debug"] = {
            "echo_upstream_body": True
        }  # https://openrouter.ai/docs/api/reference/errors-and-debugging#debug-option-shape
    extra_headers: dict[str, str] = {}

    if param.thinking:
        if param.thinking.type != "disabled" and param.thinking.budget_tokens is not None:
            extra_body["reasoning"] = {
                "max_tokens": param.thinking.budget_tokens,
                "enable": True,
            }  # OpenRouter: https://openrouter.ai/docs/use-cases/reasoning-tokens#anthropic-models-with-reasoning-tokens
        elif param.thinking.reasoning_effort is not None:
            extra_body["reasoning"] = {
                "effort": param.thinking.reasoning_effort,
            }

    if param.provider_routing:
        extra_body["provider"] = param.provider_routing.model_dump(exclude_none=True)

    if is_claude_model(param.model_id):
        extra_headers["x-anthropic-beta"] = (
            f"{ANTHROPIC_BETA_FINE_GRAINED_TOOL_STREAMING},{ANTHROPIC_BETA_INTERLEAVED_THINKING}"
        )

    payload: CompletionCreateParamsStreaming = {
        "model": str(param.model_id),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "stream": True,
        "messages": messages,
        "temperature": param.temperature,
        "max_tokens": param.max_tokens,
        "tools": tools,
        "verbosity": param.verbosity,
    }

    return payload, extra_body, extra_headers


@register(llm_param.LLMClientProtocol.OPENROUTER)
class OpenRouterClient(LLMClientABC):
    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        client = openai.AsyncOpenAI(
            api_key=config.api_key,
            base_url=OPENROUTER_BASE_URL,
            timeout=httpx.Timeout(LLM_HTTP_TIMEOUT_TOTAL, connect=LLM_HTTP_TIMEOUT_CONNECT, read=LLM_HTTP_TIMEOUT_READ),
        )
        self.client: openai.AsyncOpenAI = client

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        try:
            payload, extra_body, extra_headers = build_payload(param)
        except (ValueError, OSError) as e:
            return error_llm_stream(metadata_tracker, error=f"{e.__class__.__name__} {e!s}")

        log_debug(
            json.dumps({**payload, **extra_body}, ensure_ascii=False, default=str),
            style="yellow",
            debug_type=DebugType.LLM_PAYLOAD,
        )

        try:
            stream = await self.client.chat.completions.create(
                **payload,
                extra_body=extra_body,
                extra_headers=extra_headers,
            )
        except (openai.OpenAIError, httpx.HTTPError) as e:
            return error_llm_stream(metadata_tracker, error=f"{e.__class__.__name__} {e!s}")

        reasoning_handler = ReasoningStreamHandler(
            param_model=str(param.model_id),
            response_id=None,
        )

        def on_event(event: Any) -> None:
            log_debug(
                event.model_dump_json(exclude_none=True),
                style="blue",
                debug_type=DebugType.LLM_STREAM,
            )

        return OpenAILLMStream(
            stream,
            param=param,
            metadata_tracker=metadata_tracker,
            reasoning_handler=reasoning_handler,
            on_event=on_event,
            provider_prefix="openrouter/",
        )
