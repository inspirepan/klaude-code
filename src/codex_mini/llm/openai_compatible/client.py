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
from codex_mini.trace import log_debug


@register(LLMClientProtocol.OPENAI)
class OpenAICompatibleClient(LLMClientABC):
    def __init__(self, config: LLMConfigParameter):
        super().__init__()
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

        extra_body = {}
        if param.thinking:
            extra_body["thinking"] = param.thinking.model_dump(exclude_none=True)
        if param.provider_routing:
            extra_body["provider"] = param.provider_routing.model_dump(exclude_none=True)
        if param.plugins:
            extra_body["plugins"] = [p.model_dump(exclude_none=True) for p in param.plugins]

        if self.is_debug_mode():
            import json

            log_debug("▷▷▷ llm [Payload Messages]", json.dumps(messages, indent=2, ensure_ascii=False), style="yellow")
            log_debug(
                "▷▷▷ llm [Payload Extra Body]", json.dumps(extra_body, indent=2, ensure_ascii=False), style="yellow"
            )

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
        metadata_item = model.ResponseMetadataItem()

        turn_annotations: list[model.Annotation] | None = None

        async for event in await stream:
            if self.is_debug_mode():
                log_debug("◁◁◁ stream [SSE]", str(event), style="blue")
            if not response_id and event.id:
                response_id = event.id
                accumulated_tool_calls.response_id = response_id
                yield model.StartItem(response_id=response_id)
            if event.usage is not None:
                metadata_item.usage = convert_usage(event.usage)
            if event.model:
                metadata_item.model_name = event.model
            if provider := getattr(event, "provider", None):
                metadata_item.provider = str(provider)

            if len(event.choices) == 0:
                continue
            delta = event.choices[0].delta

            # Reasoning
            reasoning_content = ""
            if hasattr(delta, "reasoning") and getattr(delta, "reasoning"):
                reasoning_content = getattr(delta, "reasoning")
            if hasattr(delta, "reasoning_content") and getattr(delta, "reasoning_content"):
                reasoning_content = getattr(delta, "reasoning_content")
            if reasoning_content:
                stage = "reasoning"
                accumulated_reasoning.append(reasoning_content)
                yield model.ThinkingTextDelta(
                    thinking=reasoning_content,
                    response_id=response_id,
                )

            # Annotations (URL Citation)
            if hasattr(delta, "annotations") and getattr(delta, "annotations"):
                annotations = getattr(delta, "annotations")
                if annotations:
                    a = model.Annotations.validate_python(annotations)
                    if not turn_annotations:
                        turn_annotations = a
                    else:
                        turn_annotations.extend(a)

            # Assistant
            if delta.content and len(delta.content) > 0:
                if stage == "reasoning":
                    yield model.ThinkingTextItem(thinking="".join(accumulated_reasoning), response_id=response_id)
                    yield model.ReasoningItem(content="".join(accumulated_reasoning), response_id=response_id)
                stage = "assistant"
                accumulated_content.append(delta.content)
                yield model.AssistantMessageDelta(
                    content=delta.content,
                    response_id=response_id,
                )

            # Tool
            if delta.tool_calls and len(delta.tool_calls) > 0:
                if stage == "reasoning":
                    yield model.ThinkingTextItem(thinking="".join(accumulated_reasoning), response_id=response_id)
                    yield model.ReasoningItem(content="".join(accumulated_reasoning), response_id=response_id)
                elif stage == "assistant":
                    yield model.AssistantMessageItem(
                        content="".join(accumulated_content),
                        response_id=response_id,
                        annotations=turn_annotations,
                    )
                stage = "tool"
                accumulated_tool_calls.add(delta.tool_calls)

        # Finalize
        if stage == "reasoning":
            yield model.ThinkingTextItem(thinking="".join(accumulated_reasoning), response_id=response_id)
            yield model.ReasoningItem(content="".join(accumulated_reasoning), response_id=response_id)
        elif stage == "assistant":
            yield model.AssistantMessageItem(
                content="".join(accumulated_content),
                response_id=response_id,
                annotations=turn_annotations,
            )
        elif stage == "tool":
            for tool_call_item in accumulated_tool_calls.get():
                yield tool_call_item

        metadata_item.response_id = response_id
        yield metadata_item

    def model_name(self) -> str:
        return str(self.config.model)


def convert_usage(usage: openai.types.CompletionUsage) -> model.Usage:
    return model.Usage(
        input_tokens=usage.prompt_tokens,
        cached_tokens=(usage.prompt_tokens_details.cached_tokens if usage.prompt_tokens_details else 0) or 0,
        reasoning_tokens=(usage.completion_tokens_details.reasoning_tokens if usage.completion_tokens_details else 0)
        or 0,
        output_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )
