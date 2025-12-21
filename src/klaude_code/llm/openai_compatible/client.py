import json
from collections.abc import AsyncGenerator
from typing import Any, override

import httpx
import openai
from openai.types.chat.completion_create_params import CompletionCreateParamsStreaming

from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.openai_compatible.input import convert_history_to_input, convert_tool_schema
from klaude_code.llm.openai_compatible.stream import DefaultReasoningHandler, parse_chat_completions_stream
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker
from klaude_code.protocol import llm_param, model
from klaude_code.trace import DebugType, log_debug


def build_payload(param: llm_param.LLMCallParameter) -> tuple[CompletionCreateParamsStreaming, dict[str, object]]:
    """Build OpenAI API request parameters."""
    messages = convert_history_to_input(param.input, param.system, param.model)
    tools = convert_tool_schema(param.tools)

    extra_body: dict[str, object] = {}

    if param.thinking and param.thinking.type == "enabled":
        extra_body["thinking"] = {
            "type": param.thinking.type,
            "budget": param.thinking.budget_tokens,
        }

    payload: CompletionCreateParamsStreaming = {
        "model": str(param.model),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "stream": True,
        "messages": messages,
        "temperature": param.temperature,
        "max_tokens": param.max_tokens,
        "tools": tools,
        "reasoning_effort": param.thinking.reasoning_effort if param.thinking else None,
        "verbosity": param.verbosity,
    }

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
                timeout=httpx.Timeout(300.0, connect=15.0, read=285.0),
            )
        else:
            client = openai.AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=httpx.Timeout(300.0, connect=15.0, read=285.0),
            )
        self.client: openai.AsyncAzureOpenAI | openai.AsyncOpenAI = client

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> AsyncGenerator[model.ConversationItem]:
        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        payload, extra_body = build_payload(param)
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
            yield model.StreamErrorItem(error=f"{e.__class__.__name__} {e!s}")
            yield metadata_tracker.finalize()
            return

        reasoning_handler = DefaultReasoningHandler(
            param_model=str(param.model),
            response_id=None,
        )

        def on_event(event: Any) -> None:
            log_debug(
                event.model_dump_json(exclude_none=True),
                style="blue",
                debug_type=DebugType.LLM_STREAM,
            )

        async for item in parse_chat_completions_stream(
            stream,
            param=param,
            metadata_tracker=metadata_tracker,
            reasoning_handler=reasoning_handler,
            on_event=on_event,
        ):
            yield item
