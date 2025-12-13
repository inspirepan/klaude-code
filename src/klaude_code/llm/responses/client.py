import json
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, override

import httpx
import openai
from openai import AsyncAzureOpenAI, AsyncOpenAI
from openai.types import responses
from openai.types.responses.response_create_params import ResponseCreateParamsStreaming

from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.registry import register
from klaude_code.llm.responses.input import convert_history_to_input, convert_tool_schema
from klaude_code.llm.usage import MetadataTracker
from klaude_code.protocol import llm_param, model
from klaude_code.trace import DebugType, log_debug

if TYPE_CHECKING:
    from openai import AsyncStream
    from openai.types.responses import ResponseStreamEvent


def build_payload(param: llm_param.LLMCallParameter) -> ResponseCreateParamsStreaming:
    """Build OpenAI Responses API request parameters."""
    inputs = convert_history_to_input(param.input, param.model)
    tools = convert_tool_schema(param.tools)

    payload: ResponseCreateParamsStreaming = {
        "model": str(param.model),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "include": [
            "reasoning.encrypted_content",
        ],
        "store": False,
        "stream": True,
        "temperature": param.temperature,
        "max_output_tokens": param.max_tokens,
        "input": inputs,
        "instructions": param.system,
        "tools": tools,
        "prompt_cache_key": param.session_id or "",
    }

    if param.thinking and param.thinking.reasoning_effort:
        payload["reasoning"] = {
            "effort": param.thinking.reasoning_effort,
            "summary": param.thinking.reasoning_summary,
        }

    if param.verbosity:
        payload["text"] = {"verbosity": param.verbosity}

    return payload


async def parse_responses_stream(
    stream: "AsyncStream[ResponseStreamEvent]",
    param: llm_param.LLMCallParameter,
    metadata_tracker: MetadataTracker,
) -> AsyncGenerator[model.ConversationItem]:
    """Parse OpenAI Responses API stream events into ConversationItems."""
    response_id: str | None = None

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
                    response_id = event.response.id
                    yield model.StartItem(response_id=response_id)
                case responses.ResponseReasoningSummaryTextDeltaEvent() as event:
                    if event.delta:
                        metadata_tracker.record_token()
                        yield model.ReasoningTextDelta(
                            content=event.delta,
                            response_id=response_id,
                        )
                case responses.ResponseReasoningSummaryTextDoneEvent() as event:
                    if event.text:
                        yield model.ReasoningTextItem(
                            content=event.text,
                            response_id=response_id,
                            model=str(param.model),
                        )
                case responses.ResponseTextDeltaEvent() as event:
                    if event.delta:
                        metadata_tracker.record_token()
                    yield model.AssistantMessageDelta(content=event.delta, response_id=response_id)
                case responses.ResponseOutputItemAddedEvent() as event:
                    if isinstance(event.item, responses.ResponseFunctionToolCall):
                        metadata_tracker.record_token()
                        yield model.ToolCallStartItem(
                            response_id=response_id,
                            call_id=event.item.call_id,
                            name=event.item.name,
                        )
                case responses.ResponseOutputItemDoneEvent() as event:
                    match event.item:
                        case responses.ResponseReasoningItem() as item:
                            if item.encrypted_content:
                                metadata_tracker.record_token()
                                yield model.ReasoningEncryptedItem(
                                    id=item.id,
                                    encrypted_content=item.encrypted_content,
                                    response_id=response_id,
                                    model=str(param.model),
                                )
                        case responses.ResponseOutputMessage() as item:
                            metadata_tracker.record_token()
                            yield model.AssistantMessageItem(
                                content="\n".join(
                                    [
                                        part.text
                                        for part in item.content
                                        if isinstance(part, responses.ResponseOutputText)
                                    ]
                                ),
                                id=item.id,
                                response_id=response_id,
                            )
                        case responses.ResponseFunctionToolCall() as item:
                            metadata_tracker.record_token()
                            yield model.ToolCallItem(
                                name=item.name,
                                arguments=item.arguments.strip(),
                                call_id=item.call_id,
                                id=item.id,
                                response_id=response_id,
                            )
                        case _:
                            pass
                case responses.ResponseCompletedEvent() as event:
                    error_reason: str | None = None
                    if event.response.incomplete_details is not None:
                        error_reason = event.response.incomplete_details.reason
                    if event.response.usage is not None:
                        metadata_tracker.set_usage(
                            model.Usage(
                                input_tokens=event.response.usage.input_tokens,
                                output_tokens=event.response.usage.output_tokens,
                                cached_tokens=event.response.usage.input_tokens_details.cached_tokens,
                                reasoning_tokens=event.response.usage.output_tokens_details.reasoning_tokens,
                                context_size=event.response.usage.total_tokens,
                                context_limit=param.context_limit,
                                max_tokens=param.max_tokens,
                            )
                        )
                    metadata_tracker.set_model_name(str(param.model))
                    metadata_tracker.set_response_id(response_id)
                    yield metadata_tracker.finalize()
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
                        yield model.StreamErrorItem(error=error_message)
                case _:
                    log_debug(
                        "[Unhandled stream event]",
                        str(event),
                        style="red",
                        debug_type=DebugType.LLM_STREAM,
                    )
    except (openai.OpenAIError, httpx.HTTPError) as e:
        yield model.StreamErrorItem(error=f"{e.__class__.__name__} {e!s}")


@register(llm_param.LLMClientProtocol.RESPONSES)
class ResponsesClient(LLMClientABC):
    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        if config.is_azure:
            if not config.base_url:
                raise ValueError("Azure endpoint is required")
            client = AsyncAzureOpenAI(
                api_key=config.api_key,
                azure_endpoint=str(config.base_url),
                api_version=config.azure_api_version,
                timeout=httpx.Timeout(300.0, connect=15.0, read=285.0),
            )
        else:
            client = AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=httpx.Timeout(300.0, connect=15.0, read=285.0),
            )
        self.client: AsyncAzureOpenAI | AsyncOpenAI = client

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> AsyncGenerator[model.ConversationItem]:
        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        payload = build_payload(param)

        log_debug(
            json.dumps(payload, ensure_ascii=False, default=str),
            style="yellow",
            debug_type=DebugType.LLM_PAYLOAD,
        )
        try:
            stream = await self.client.responses.create(
                **payload,
                extra_headers={"extra": json.dumps({"session_id": param.session_id}, sort_keys=True)},
            )
        except (openai.OpenAIError, httpx.HTTPError) as e:
            yield model.StreamErrorItem(error=f"{e.__class__.__name__} {e!s}")
            return

        async for item in parse_responses_stream(stream, param, metadata_tracker):
            yield item
