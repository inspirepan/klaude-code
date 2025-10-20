import json
import time
from collections.abc import AsyncGenerator
from typing import override

import httpx
from openai import AsyncAzureOpenAI, AsyncOpenAI, RateLimitError
from openai.types import responses

from codex_mini.llm.client import LLMClientABC
from codex_mini.llm.registry import register
from codex_mini.llm.responses.input import convert_history_to_input, convert_tool_schema
from codex_mini.protocol.llm_parameter import (
    LLMCallParameter,
    LLMClientProtocol,
    LLMConfigParameter,
    apply_config_defaults,
)
from codex_mini.protocol.model import (
    AssistantMessageDelta,
    AssistantMessageItem,
    ConversationItem,
    ReasoningItem,
    ResponseMetadataItem,
    StartItem,
    StreamErrorItem,
    ThinkingTextDelta,
    ToolCallItem,
    Usage,
)
from codex_mini.trace import log_debug


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

        parallel_tool_calls = True if param.model and not param.model.startswith("gpt-5-codex") else False

        if self.is_debug_mode():
            payload: dict[str, object] = {
                "model": str(param.model),
                "tool_choice": "auto",
                "parallel_tool_calls": parallel_tool_calls,
                "include": [
                    "reasoning.encrypted_content",
                ],
                "store": param.store,
                "previous_response_id": param.previous_response_id,
                "stream": True,
                "temperature": param.temperature,
                "max_output_tokens": param.max_tokens,
                "input": inputs,
                "instructions": param.system,
                "tools": convert_tool_schema(param.tools),
                "text": {
                    "verbosity": param.verbosity,
                },
                "reasoning": {
                    "effort": param.reasoning.effort,
                    "summary": param.reasoning.summary,
                }
                if param.reasoning
                else None,
            }
            # Remove None values
            payload = {k: v for k, v in payload.items() if v is not None}

            log_debug("▷▷▷ llm [Complete Payload]", json.dumps(payload, ensure_ascii=False), style="yellow")

        stream = self.client.responses.create(
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
            tools=convert_tool_schema(param.tools),
            text={
                "verbosity": param.verbosity,
            },
            reasoning={
                "effort": param.reasoning.effort,
                "summary": param.reasoning.summary,
            }
            if param.reasoning
            else None,
            extra_headers={"extra": json.dumps({"session_id": param.session_id})},
        )

        try:
            async for event in await stream:
                if self.is_debug_mode():
                    log_debug(f"◁◁◁ stream [SSE {event.type}]", str(event), style="blue")
                match event:
                    case responses.ResponseCreatedEvent() as event:
                        response_id = event.response.id
                        yield StartItem(response_id=response_id)
                    case responses.ResponseReasoningSummaryTextDeltaEvent() as event:
                        if first_token_time is None:
                            first_token_time = time.time()
                        last_token_time = time.time()
                        yield ThinkingTextDelta(
                            thinking=event.delta,
                            response_id=response_id,
                        )
                    case responses.ResponseReasoningSummaryTextDoneEvent() as event:
                        pass
                    case responses.ResponseTextDeltaEvent() as event:
                        if first_token_time is None:
                            first_token_time = time.time()
                        last_token_time = time.time()
                        yield AssistantMessageDelta(content=event.delta, response_id=response_id)
                    case responses.ResponseOutputItemDoneEvent() as event:
                        match event.item:
                            case responses.ResponseReasoningItem() as item:
                                summary = [summary.text for summary in item.summary]
                                yield ReasoningItem(
                                    id=item.id,
                                    summary=summary,
                                    content="\n".join([content.text for content in item.content])
                                    if item.content
                                    else None,
                                    encrypted_content=item.encrypted_content,
                                    response_id=response_id,
                                    model=param.model,
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
                            if self.is_debug_mode():
                                log_debug("◁◁◁ stream [LLM Status Warning]", error_message, style="red")
                            yield StreamErrorItem(error=error_message)
                    case _:
                        if self.is_debug_mode():
                            log_debug("◁◁◁ stream [Unhandled Event]", str(event), style="red")
        except RateLimitError as e:
            yield StreamErrorItem(error=f"{e.__class__.__name__} {str(e)}")
