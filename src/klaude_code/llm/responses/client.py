import json
import time
from collections.abc import AsyncGenerator
from typing import Callable, ParamSpec, TypeVar, override

import httpx
from openai import AsyncAzureOpenAI, AsyncOpenAI, RateLimitError
from openai.types import responses

from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.registry import register
from klaude_code.llm.responses.input import convert_history_to_input, convert_tool_schema
from klaude_code.protocol.llm_parameter import (
    LLMCallParameter,
    LLMClientProtocol,
    LLMConfigParameter,
    apply_config_defaults,
)
from klaude_code.protocol.model import (
    AssistantMessageDelta,
    AssistantMessageItem,
    ConversationItem,
    ReasoningEncryptedItem,
    ReasoningTextItem,
    ResponseMetadataItem,
    StartItem,
    StreamErrorItem,
    ToolCallItem,
    Usage,
)
from klaude_code.trace import DebugType, log_debug

P = ParamSpec("P")
R = TypeVar("R")


def call_with_logged_payload(func: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """Call an SDK function while logging the JSON payload.

    The function reuses the original callable's type signature via ParamSpec
    so static type checkers can validate arguments at the call site.
    """

    payload = {k: v for k, v in kwargs.items() if v is not None}
    log_debug(
        "Complete payload",
        json.dumps(payload, ensure_ascii=False, default=str),
        style="yellow",
        debug_type=DebugType.LLM_PAYLOAD,
    )
    return func(*args, **kwargs)


@register(LLMClientProtocol.RESPONSES)
class ResponsesClient(LLMClientABC):
    def __init__(self, config: LLMConfigParameter):
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
    def create(cls, config: LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: LLMCallParameter) -> AsyncGenerator[ConversationItem, None]:
        param = apply_config_defaults(param, self.get_llm_config())

        request_start_time = time.time()
        first_token_time: float | None = None
        last_token_time: float | None = None
        response_id: str | None = None

        inputs = convert_history_to_input(param.input, param.model)
        tools = convert_tool_schema(param.tools)

        parallel_tool_calls = True

        stream = call_with_logged_payload(
            self.client.responses.create,
            model=str(param.model),
            tool_choice="auto",
            parallel_tool_calls=parallel_tool_calls,  # OpenAI's Codex is always False, we try to enable it here. It seems gpt-5-codex has bugs when parallel_tool_calls is True.
            include=[
                "reasoning.encrypted_content",
            ],
            store=param.store,
            previous_response_id=param.previous_response_id,
            stream=True,
            temperature=param.temperature,
            max_output_tokens=param.max_tokens,
            input=inputs,
            instructions=param.system,
            tools=tools,
            text={
                "verbosity": param.verbosity,
            },
            reasoning={
                "effort": param.thinking.reasoning_effort,
                "summary": param.thinking.reasoning_summary,
            }
            if param.thinking and param.thinking.reasoning_effort
            else None,
            extra_headers={"extra": json.dumps({"session_id": param.session_id})},
        )

        try:
            async for event in await stream:
                log_debug(
                    f"[{event.type}]",
                    event.model_dump_json(exclude_none=True),
                    style="blue",
                    debug_type=DebugType.LLM_STREAM,
                )
                match event:
                    case responses.ResponseCreatedEvent() as event:
                        response_id = event.response.id
                        yield StartItem(response_id=response_id)
                    case responses.ResponseReasoningSummaryTextDoneEvent() as event:
                        if event.text:
                            yield ReasoningTextItem(
                                content=event.text,
                                response_id=response_id,
                                model=str(param.model),
                            )
                    case responses.ResponseTextDeltaEvent() as event:
                        if first_token_time is None:
                            first_token_time = time.time()
                        last_token_time = time.time()
                        yield AssistantMessageDelta(content=event.delta, response_id=response_id)
                    case responses.ResponseOutputItemDoneEvent() as event:
                        match event.item:
                            case responses.ResponseReasoningItem() as item:
                                if item.encrypted_content:
                                    yield ReasoningEncryptedItem(
                                        id=item.id,
                                        encrypted_content=item.encrypted_content,
                                        response_id=response_id,
                                        model=str(param.model),
                                    )
                            case responses.ResponseOutputMessage() as item:
                                yield AssistantMessageItem(
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
                                if first_token_time is None:
                                    first_token_time = time.time()
                                last_token_time = time.time()
                                yield ToolCallItem(
                                    name=item.name,
                                    arguments=item.arguments.strip(),
                                    call_id=item.call_id,
                                    id=item.id,
                                    response_id=response_id,
                                )
                            case _:
                                pass
                    case responses.ResponseCompletedEvent() as event:
                        usage: Usage | None = None
                        error_reason: str | None = None
                        if event.response.incomplete_details is not None:
                            error_reason = event.response.incomplete_details.reason
                        if event.response.usage is not None:
                            total_tokens = event.response.usage.total_tokens
                            context_usage_percent = (
                                (total_tokens / param.context_limit) * 100 if param.context_limit else None
                            )

                            throughput_tps: float | None = None
                            first_token_latency_ms: float | None = None

                            if first_token_time is not None:
                                first_token_latency_ms = (first_token_time - request_start_time) * 1000

                            if (
                                first_token_time is not None
                                and last_token_time is not None
                                and event.response.usage.output_tokens > 0
                            ):
                                time_duration = last_token_time - first_token_time
                                if time_duration >= 0.15:
                                    throughput_tps = event.response.usage.output_tokens / time_duration

                            usage = Usage(
                                input_tokens=event.response.usage.input_tokens,
                                cached_tokens=event.response.usage.input_tokens_details.cached_tokens,
                                reasoning_tokens=event.response.usage.output_tokens_details.reasoning_tokens,
                                output_tokens=event.response.usage.output_tokens,
                                total_tokens=total_tokens,
                                context_usage_percent=context_usage_percent,
                                throughput_tps=throughput_tps,
                                first_token_latency_ms=first_token_latency_ms,
                            )
                        yield ResponseMetadataItem(
                            usage=usage,
                            response_id=response_id,
                            model_name=str(param.model),
                            status=event.response.status,
                            error_reason=error_reason,
                        )
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
                            yield StreamErrorItem(error=error_message)
                    case _:
                        log_debug("[Unhandled stream event]", str(event), style="red", debug_type=DebugType.LLM_STREAM)
        except RateLimitError as e:
            yield StreamErrorItem(error=f"{e.__class__.__name__} {str(e)}")
