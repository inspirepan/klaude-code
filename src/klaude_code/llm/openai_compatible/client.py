import asyncio
from typing import Literal, cast, override

import openai
from openai.types.chat.completion_create_params import CompletionCreateParamsStreaming

from klaude_code.llm.client import LLMClientABC, LLMStreamABC, session_headers
from klaude_code.llm.http import create_async_http_client, create_http_timeout
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.openai_compatible.input import convert_history_to_input, convert_tool_schema
from klaude_code.llm.openai_compatible.request import request_chat_completions
from klaude_code.llm.openai_compatible.stream import DefaultReasoningHandler
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.protocol import llm_param

_OPENAI_USER_AGENT = "klaude-code/2"


def build_payload(param: llm_param.LLMCallParameter) -> tuple[CompletionCreateParamsStreaming, dict[str, object]]:
    messages = convert_history_to_input(param.input, param.system, param.model_id)
    tools = convert_tool_schema(param.tools)

    extra_body: dict[str, object] = {}

    if param.thinking and param.thinking.type == "enabled":
        extra_body["thinking"] = {
            "type": param.thinking.type,
            "budget": param.thinking.budget_tokens,
        }

    temperature = param.temperature
    reasoning_effort = param.thinking.reasoning_effort if param.thinking else None

    payload: CompletionCreateParamsStreaming = {
        "model": str(param.model_id),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "stream": True,
        "messages": messages,
        "max_tokens": param.max_tokens,
        "tools": tools,
    }

    # Strict OpenAI-compatible upstreams (e.g. opencode zen -> DeepSeek) reject
    # explicit nulls for these optional fields; only send them when set.
    if temperature is not None:
        payload["temperature"] = temperature
    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort

    if param.verbosity:
        # Our verbosity literal ("max") is wider than the SDK's TypedDict declaration.
        payload["verbosity"] = cast(Literal["low", "medium", "high"], param.verbosity)

    return payload, extra_body


@register(llm_param.LLMClientProtocol.OPENAI)
class OpenAICompatibleClient(LLMClientABC):
    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        if config.is_azure:
            if not config.base_url:
                raise ValueError("Azure endpoint is required")
            client = openai.AsyncAzureOpenAI(
                api_key=config.api_key,
                azure_endpoint=str(config.base_url),
                api_version=config.azure_api_version,
                default_headers={"User-Agent": _OPENAI_USER_AGENT},
                timeout=create_http_timeout(),
                http_client=create_async_http_client(),
            )
        else:
            client = openai.AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                default_headers={"User-Agent": _OPENAI_USER_AGENT},
                timeout=create_http_timeout(),
                http_client=create_async_http_client(),
            )
        self.client: openai.AsyncAzureOpenAI | openai.AsyncOpenAI = client

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        try:
            # Payload building re-encodes history images; keep it off the event loop.
            payload, extra_body = await asyncio.to_thread(build_payload, param)
        except (ValueError, OSError) as e:
            return error_llm_stream(metadata_tracker, error=f"{e.__class__.__name__} {e!s}")

        extra_headers = session_headers(self.get_llm_config().provider_name, param.session_id)

        return await request_chat_completions(
            self.client,
            param=param,
            payload=payload,
            extra_body=extra_body,
            extra_headers=extra_headers,
            metadata_tracker=metadata_tracker,
            reasoning_handler=DefaultReasoningHandler(param_model=str(param.model_id), response_id=None),
        )
