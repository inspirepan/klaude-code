from collections.abc import AsyncGenerator
from typing import Literal, override

import httpx
import openai

from codex_mini.llm.client import LLMClientABC
from codex_mini.llm.openai_compatible.input import convert_history_to_input, convert_tool_schema
from codex_mini.llm.openai_compatible.tool_call_accumulator import BasicToolCallAccumulator, ToolCallAccumulatorABC
from codex_mini.llm.registry import register
from codex_mini.protocol import model
from codex_mini.protocol.llm_parameter import (
    LLMCallParameter,
    LLMClientProtocol,
    LLMConfigParameter,
    apply_config_defaults,
)


@register(LLMClientProtocol.OPENAI)
class OpenAICompatibleClient(LLMClientABC):
    def __init__(self, config: LLMConfigParameter):
        self.config: LLMConfigParameter = config
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
    def create(cls, config: LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: LLMCallParameter) -> AsyncGenerator[model.ConversationItem, None]:
        param = apply_config_defaults(param, self.config)
        messages = convert_history_to_input(param.input, param.system)
        tools = convert_tool_schema(param.tools)

        # import json

        # print(json.dumps(messages, indent=2, ensure_ascii=False))

        extra_body = {}
        if param.thinking:
            extra_body["thinking"] = {
                "type": param.thinking.type,
                "budget_tokens": param.thinking.budget_tokens,
            }

        stream = self.client.chat.completions.create(
            model=str(param.model),
            tool_choice="auto",
            parallel_tool_calls=True,
            stream=True,
            messages=messages,
            temperature=param.temperature,
            max_tokens=param.max_tokens,
            tools=tools,
            reasoning_effort=param.reasoning.effort if param.reasoning else None,
            verbosity=param.verbosity,
            extra_body=extra_body,  # pyright: ignore[reportUnknownArgumentType]
        )

        stage: Literal["waiting", "reasoning", "assistant", "tool", "done"] = "waiting"
        accumulated_reasoning: list[str] = []
        accumulated_content: list[str] = []
        accumulated_tool_calls: ToolCallAccumulatorABC = BasicToolCallAccumulator()
        response_id: str | None = None

        async for event in await stream:
            if not response_id and event.id:
                response_id = event.id
                accumulated_tool_calls.response_id = response_id
                yield model.StartItem(response_id=response_id)
            if event.usage is not None:
                yield model.ResponseMetadataItem(
                    usage=convert_usage(event.usage),
                    response_id=response_id,
                    model_name=str(param.model),
                )
            if len(event.choices) == 0:
                continue
            delta = event.choices[0].delta
            if hasattr(delta, "reasoning") and getattr(delta, "reasoning"):
                reasoning: str = getattr(delta, "reasoning")
                stage = "reasoning"
                accumulated_reasoning.append(reasoning)
                yield model.ThinkingTextDelta(
                    thinking=reasoning,
                    response_id=response_id,
                )
            if delta.content and len(delta.content) > 0:
                if stage == "reasoning":
                    yield model.ThinkingTextItem(thinking="".join(accumulated_reasoning), response_id=response_id)
                stage = "assistant"
                accumulated_content.append(delta.content)
                yield model.AssistantMessageDelta(
                    content=delta.content,
                    response_id=response_id,
                )
            if delta.tool_calls and len(delta.tool_calls) > 0:
                if stage == "reasoning":
                    yield model.ThinkingTextItem(thinking="".join(accumulated_reasoning), response_id=response_id)
                elif stage == "assistant":
                    yield model.AssistantMessageItem(
                        content="".join(accumulated_content),
                        response_id=response_id,
                    )
                stage = "tool"
                accumulated_tool_calls.add(delta.tool_calls)

        if stage == "reasoning":
            yield model.ThinkingTextItem(thinking="".join(accumulated_reasoning), response_id=response_id)
        elif stage == "assistant":
            yield model.AssistantMessageItem(
                content="".join(accumulated_content),
                response_id=response_id,
            )
        elif stage == "tool":
            for tool_call_item in accumulated_tool_calls.get():
                yield tool_call_item


def convert_usage(usage: openai.types.CompletionUsage) -> model.Usage:
    return model.Usage(
        input_tokens=usage.prompt_tokens,
        cached_tokens=(usage.prompt_tokens_details.cached_tokens if usage.prompt_tokens_details else 0) or 0,
        reasoning_tokens=(usage.completion_tokens_details.reasoning_tokens if usage.completion_tokens_details else 0)
        or 0,
        output_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )
