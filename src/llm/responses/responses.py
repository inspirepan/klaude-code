from collections.abc import AsyncGenerator
from typing import override

from openai import AsyncAzureOpenAI, AsyncOpenAI
from openai.types.responses import (
    ResponseCompletedEvent,
    ResponseCreatedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseReasoningItem,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseReasoningSummaryTextDoneEvent,
    ResponseTextDeltaEvent,
)

from src.llm.client import LLMClient
from src.llm.registry import register
from src.llm.responses.input import convert_history_to_input, convert_tool_schema
from src.protocal.llm_parameter import (
    LLMCallParameter,
    LLMConfigParameter,
    merge_llm_parameter,
)
from src.protocal.model import AssistantMessage  # ToolCallItem,
from src.protocal.model import (
    AssistantMessageTextDelta,
    ContentPart,
    ReasoningItem,
    ResponseItem,
    ResponseMetadataItem,
    StartItem,
    ThinkingTextDelta,
    ThinkingTextDone,
    Usage,
)


@register("responses")
class ResponsesClient(LLMClient):
    def __init__(self, config: LLMConfigParameter):
        self.config: LLMConfigParameter = config
        if config.is_azure:
            if not config.base_url:
                raise ValueError("Azure endpoint is required")
            client = AsyncAzureOpenAI(
                api_key=config.api_key,
                azure_endpoint=str(config.base_url),
                api_version=config.azure_api_version,
            )
        else:
            client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        self.client: AsyncAzureOpenAI | AsyncOpenAI = client

    @classmethod
    @override
    def create(cls, config: LLMConfigParameter) -> "LLMClient":
        return cls(config)

    @override
    async def Call(self, param: LLMCallParameter) -> AsyncGenerator[ResponseItem, None]:
        param = merge_llm_parameter(param, self.config)

        if param.model == "gpt-5-2025-08-07":
            param.temperature = 1.0

        response_id: str | None = None

        input = convert_history_to_input(param.input)

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
            input=input,
            instructions=param.system,
            tools=convert_tool_schema(param.tools),
            reasoning={
                "effort": param.reasoning.effort,
                "summary": param.reasoning.summary,
            }
            if param.reasoning
            else None,
        )

        async for response in await stream:
            match response:
                case ResponseCreatedEvent() as event:
                    response_id = event.response.id
                    yield StartItem(response_id=response_id)
                case ResponseReasoningSummaryTextDeltaEvent() as event:
                    yield ThinkingTextDelta(
                        thinking=event.delta, response_id=response_id
                    )
                case ResponseReasoningSummaryTextDoneEvent() as event:
                    yield ThinkingTextDone(thinking=event.text, response_id=response_id)
                case ResponseTextDeltaEvent() as event:
                    yield AssistantMessageTextDelta(
                        content=event.delta, response_id=response_id
                    )
                case ResponseOutputItemDoneEvent() as event:
                    match event.item:
                        case ResponseReasoningItem() as item:
                            yield ReasoningItem(
                                id=item.id,
                                summary=[summary.text for summary in item.summary],
                                content=[
                                    ContentPart(text=content.text)
                                    for content in item.content
                                ]
                                if item.content
                                else None,
                                encrypted_content=item.encrypted_content,
                                response_id=response_id,
                            )
                        case ResponseOutputMessage() as item:
                            yield AssistantMessage(
                                content=[
                                    ContentPart(text=part.text)
                                    for part in item.content
                                    if isinstance(part, ResponseOutputText)
                                ],
                                id=item.id,
                                response_id=response_id,
                            )
                        case _:
                            pass
                case ResponseCompletedEvent() as event:
                    usage: Usage | None = None
                    if event.response.usage is not None:
                        usage = Usage(
                            input_tokens=event.response.usage.input_tokens,
                            cached_tokens=event.response.usage.input_tokens
                            - event.response.usage.input_tokens_details.cached_tokens,
                            reasoning_tokens=event.response.usage.output_tokens_details.reasoning_tokens,
                            output_tokens=event.response.usage.output_tokens
                            - event.response.usage.output_tokens_details.reasoning_tokens,
                            total_tokens=event.response.usage.total_tokens,
                        )

                    yield ResponseMetadataItem(
                        usage=usage,
                        response_id=response_id,
                    )
                case _:
                    pass
