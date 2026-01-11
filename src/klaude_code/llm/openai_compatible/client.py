import json
from typing import Any, override

import httpx
import openai
from openai.types.chat.completion_create_params import CompletionCreateParamsStreaming

from klaude_code.const import LLM_HTTP_TIMEOUT_CONNECT, LLM_HTTP_TIMEOUT_READ, LLM_HTTP_TIMEOUT_TOTAL
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.openai_compatible.input import convert_history_to_input, convert_tool_schema
from klaude_code.llm.openai_compatible.stream import DefaultReasoningHandler, OpenAILLMStream
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import llm_param


def build_payload(param: llm_param.LLMCallParameter) -> tuple[CompletionCreateParamsStreaming, dict[str, object]]:
    """Build OpenAI API request parameters."""
    messages = convert_history_to_input(param.input, param.system, param.model_id)
    tools = convert_tool_schema(param.tools)

    extra_body: dict[str, object] = {}

    if param.thinking and param.thinking.type == "enabled":
        extra_body["thinking"] = {
            "type": param.thinking.type,
            "budget": param.thinking.budget_tokens,
        }

    payload: CompletionCreateParamsStreaming = {
        "model": str(param.model_id),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "stream": True,
        "messages": messages,
        "temperature": param.temperature,
        "max_tokens": param.max_tokens,
        "tools": tools,
        "reasoning_effort": param.thinking.reasoning_effort if param.thinking else None,
    }

    if param.verbosity:
        payload["verbosity"] = param.verbosity

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
                timeout=httpx.Timeout(
                    LLM_HTTP_TIMEOUT_TOTAL, connect=LLM_HTTP_TIMEOUT_CONNECT, read=LLM_HTTP_TIMEOUT_READ
                ),
            )
        else:
            client = openai.AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=httpx.Timeout(
                    LLM_HTTP_TIMEOUT_TOTAL, connect=LLM_HTTP_TIMEOUT_CONNECT, read=LLM_HTTP_TIMEOUT_READ
                ),
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
            payload, extra_body = build_payload(param)
        except (ValueError, OSError) as e:
            return error_llm_stream(metadata_tracker, error=f"{e.__class__.__name__} {e!s}")

        extra_headers: dict[str, str] = {"extra": json.dumps({"session_id": param.session_id}, sort_keys=True)}

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

        reasoning_handler = DefaultReasoningHandler(
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
        )
