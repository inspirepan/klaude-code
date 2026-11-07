from typing import cast

import httpx
import openai
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.completion_create_params import CompletionCreateParamsStreaming

from klaude_code.llm.client import LLMStreamABC
from klaude_code.llm.openai_compatible.stream import OpenAILLMStream, ReasoningHandlerABC
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.log import DebugType, debug_json, log_debug
from klaude_code.protocol import llm_param


async def request_chat_completions(
    client: openai.AsyncOpenAI,
    *,
    param: llm_param.LLMCallParameter,
    payload: CompletionCreateParamsStreaming,
    extra_body: dict[str, object],
    extra_headers: dict[str, str],
    metadata_tracker: MetadataTracker,
    reasoning_handler: ReasoningHandlerABC,
    timeout: float | httpx.Timeout | openai.NotGiven = openai.NOT_GIVEN,
    provider_prefix: str = "",
) -> LLMStreamABC:
    log_debug(
        lambda: debug_json({**payload, **extra_body}),
        debug_type=DebugType.LLM_PAYLOAD,
    )

    try:
        stream = await client.chat.completions.create(
            **payload,
            extra_body=extra_body,
            extra_headers=extra_headers,
            timeout=timeout,
        )
    except (openai.OpenAIError, httpx.HTTPError) as e:
        return error_llm_stream(metadata_tracker, error=f"{e.__class__.__name__} {e!s}")

    def on_event(event: object) -> None:
        log_debug(
            cast(ChatCompletionChunk, event).model_dump_json(exclude_none=True),
            debug_type=DebugType.LLM_STREAM,
        )

    return OpenAILLMStream(
        stream,
        param=param,
        metadata_tracker=metadata_tracker,
        reasoning_handler=reasoning_handler,
        on_event=on_event,
        provider_prefix=provider_prefix,
    )
