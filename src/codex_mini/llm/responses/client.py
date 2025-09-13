from collections.abc import AsyncGenerator
from typing import override

import httpx
from openai import AsyncAzureOpenAI, AsyncOpenAI
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
    ThinkingTextDelta,
    ThinkingTextItem,
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

        response_id: str | None = None

        inputs = convert_history_to_input(param.input, param.model)

        if self.is_debug_mode():
            import json

            payload: dict[str, object] = {
                "model": str(param.model),
                "tool_choice": "auto",
                "parallel_tool_calls": False,
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

            log_debug("▷▷▷ llm [Complete Payload]", json.dumps(payload, indent=2, ensure_ascii=False), style="yellow")

        stream = self.client.responses.create(
            model=str(param.model),
            tool_choice="auto",
            parallel_tool_calls=False,
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
        )

        async for event in await stream:
            if self.is_debug_mode():
                log_debug(f"◁◁◁ stream [SSE {event.type}]", str(event), style="blue")
            match event:
                case responses.ResponseCreatedEvent() as event:
                    response_id = event.response.id
                    yield StartItem(response_id=response_id)
                case responses.ResponseReasoningSummaryTextDeltaEvent() as event:
                    yield ThinkingTextDelta(thinking=event.delta, response_id=response_id)
                case responses.ResponseReasoningSummaryTextDoneEvent() as event:
                    yield ThinkingTextItem(thinking=event.text, response_id=response_id)
                case responses.ResponseTextDeltaEvent() as event:
                    yield AssistantMessageDelta(content=event.delta, response_id=response_id)
                case responses.ResponseOutputItemDoneEvent() as event:
                    match event.item:
                        case responses.ResponseReasoningItem() as item:
                            yield ReasoningItem(
                                id=item.id,
                                summary=[summary.text for summary in item.summary],
                                content="\n".join([content.text for content in item.content]) if item.content else None,
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
                            yield ToolCallItem(
                                name=item.name,
                                arguments=item.arguments,
                                call_id=item.call_id,
                                id=item.id,
                                response_id=response_id,
                            )
                        case _:
                            pass
                case responses.ResponseCompletedEvent() as event:
                    usage: Usage | None = None
                    if event.response.usage is not None:
                        total_tokens = event.response.usage.total_tokens
                        context_usage_percent = (
                            (total_tokens / param.context_limit) * 100 if param.context_limit else None
                        )
                        usage = Usage(
                            input_tokens=event.response.usage.input_tokens,
                            cached_tokens=event.response.usage.input_tokens_details.cached_tokens,
                            reasoning_tokens=event.response.usage.output_tokens_details.reasoning_tokens,
                            output_tokens=event.response.usage.output_tokens,
                            total_tokens=total_tokens,
                            context_usage_percent=context_usage_percent,
                        )
                    yield ResponseMetadataItem(
                        usage=usage,
                        response_id=response_id,
                        model_name=str(param.model),
                    )
                case _:
                    pass
