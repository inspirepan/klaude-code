import time
from collections.abc import AsyncGenerator
from typing import Literal, override

import httpx
import openai
from pydantic import BaseModel

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
from codex_mini.trace import log, log_debug


class ReasoningDetail(BaseModel):
    """OpenRouter's https://openrouter.ai/docs/use-cases/reasoning-tokens#reasoning_details-array-structure"""

    type: str
    format: str
    index: int
    id: str | None = None
    data: str | None = None  # OpenAI's encrypted content
    summary: str | None = None
    signature: str | None = None  # Claude's signature


@register(LLMClientProtocol.OPENAI)
class OpenAICompatibleClient(LLMClientABC):
    def __init__(self, config: LLMConfigParameter):
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
    def create(cls, config: LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: LLMCallParameter) -> AsyncGenerator[model.ConversationItem, None]:
        param = apply_config_defaults(param, self.get_llm_config())
        messages = convert_history_to_input(param.input, param.system, param.model)
        tools = convert_tool_schema(param.tools)

        request_start_time = time.time()
        first_token_time: float | None = None
        last_token_time: float | None = None

        extra_body = {}
        if param.thinking:
            if self.get_llm_config().is_openrouter():
                extra_body["reasoning"] = {
                    "max_tokens": param.thinking.budget_tokens,
                    "enable": True,
                }  # OpenRouter: https://openrouter.ai/docs/use-cases/reasoning-tokens#anthropic-models-with-reasoning-tokens
            else:
                extra_body["thinking"] = param.thinking.model_dump(exclude_none=True)  # Claude or Gemini
        if param.provider_routing:
            extra_body["provider"] = param.provider_routing.model_dump(exclude_none=True)
        if param.plugins:
            extra_body["plugins"] = [p.model_dump(exclude_none=True) for p in param.plugins]

        if self.is_debug_mode():
            import json

            payload: dict[str, object] = {
                "model": str(param.model),
                "tool_choice": "auto",
                "parallel_tool_calls": True,
                "stream": True,
                "messages": messages,
                "temperature": param.temperature,
                "max_tokens": param.max_tokens,
                "tools": tools,
                "reasoning_effort": param.reasoning.effort if param.reasoning else None,
                "verbosity": param.verbosity,
                **extra_body,
            }
            # Remove None values
            payload = {k: v for k, v in payload.items() if v is not None}

            log_debug("▷▷▷ llm [Complete Payload]", json.dumps(payload, indent=2, ensure_ascii=False), style="yellow")

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

        reasoning_encrypted_content: str | None = None
        reasoning_format: str | None = None
        reasoning_id: str | None = None

        turn_annotations: list[model.Annotation] | None = None

        async for event in await stream:
            if self.is_debug_mode():
                log_debug("◁◁◁ stream [SSE]", str(event), style="blue")
            if not response_id and event.id:
                response_id = event.id
                accumulated_tool_calls.response_id = response_id
                yield model.StartItem(response_id=response_id)
            if event.usage is not None and event.usage.completion_tokens is not None:  # pyright: ignore[reportUnnecessaryComparison] gcp gemini will return None usage field
                metadata_item.usage = convert_usage(event.usage, param.context_limit)
            if event.model:
                metadata_item.model_name = event.model
            if provider := getattr(event, "provider", None):
                metadata_item.provider = str(provider)

            if len(event.choices) == 0:
                continue
            delta = event.choices[0].delta

            # Support Kimi K2'2 usage field in choice
            if hasattr(event.choices[0], "usage") and getattr(event.choices[0], "usage"):
                metadata_item.usage = convert_usage(
                    openai.types.CompletionUsage.model_validate(getattr(event.choices[0], "usage")), param.context_limit
                )

            # Reasoning
            reasoning_content = ""
            if hasattr(delta, "reasoning") and getattr(delta, "reasoning"):
                reasoning_content = getattr(delta, "reasoning")
            if hasattr(delta, "reasoning_content") and getattr(delta, "reasoning_content"):
                reasoning_content = getattr(delta, "reasoning_content")
            if reasoning_content:
                if first_token_time is None:
                    first_token_time = time.time()
                last_token_time = time.time()
                stage = "reasoning"
                accumulated_reasoning.append(reasoning_content)
                yield model.ThinkingTextDelta(
                    thinking=reasoning_content,
                    response_id=response_id,
                )

            if hasattr(delta, "reasoning_details") and getattr(delta, "reasoning_details"):
                reasoning_details = getattr(delta, "reasoning_details")
                for item in reasoning_details:
                    try:
                        reasoning_detail = ReasoningDetail.model_validate(item)
                        if reasoning_detail.type == "reasoning.encrypted":
                            # GPT-5
                            reasoning_encrypted_content = reasoning_detail.data
                            reasoning_id = reasoning_detail.id
                            reasoning_format = reasoning_detail.format
                            break
                        elif reasoning_detail.type == "reasoning.text" and reasoning_detail.signature:
                            # Claude
                            reasoning_encrypted_content = reasoning_detail.signature
                            reasoning_id = reasoning_detail.id
                            reasoning_format = reasoning_detail.format
                            break

                    except Exception as e:
                        log("reasoning_details error", str(e), style="red")

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
            if delta.content and (
                stage == "assistant" or delta.content.strip()
            ):  # Process all content in assistant stage, filter empty content in reasoning stage
                if first_token_time is None:
                    first_token_time = time.time()
                last_token_time = time.time()
                if stage == "reasoning":
                    yield model.ReasoningItem(
                        id=reasoning_id,
                        content="".join(accumulated_reasoning),
                        response_id=response_id,
                        encrypted_content=reasoning_encrypted_content,
                        format=reasoning_format,
                        model=param.model,
                    )
                stage = "assistant"
                accumulated_content.append(delta.content)
                yield model.AssistantMessageDelta(
                    content=delta.content,
                    response_id=response_id,
                )

            # Tool
            if delta.tool_calls and len(delta.tool_calls) > 0:
                if first_token_time is None:
                    first_token_time = time.time()
                last_token_time = time.time()
                if stage == "reasoning":
                    yield model.ReasoningItem(
                        id=reasoning_id,
                        content="".join(accumulated_reasoning),
                        response_id=response_id,
                        encrypted_content=reasoning_encrypted_content,
                        format=reasoning_format,
                        model=param.model,
                    )
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
            yield model.ReasoningItem(
                id=reasoning_id,
                content="".join(accumulated_reasoning),
                response_id=response_id,
                encrypted_content=reasoning_encrypted_content,
                format=reasoning_format,
                model=param.model,
            )
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

        # Calculate performance metrics if we have timing data
        if metadata_item.usage and first_token_time is not None:
            metadata_item.usage.first_token_latency_ms = (first_token_time - request_start_time) * 1000

            if last_token_time is not None and metadata_item.usage.output_tokens > 0:
                time_duration = last_token_time - first_token_time
                if time_duration >= 0.15:
                    metadata_item.usage.throughput_tps = metadata_item.usage.output_tokens / time_duration

        yield metadata_item


def convert_usage(usage: openai.types.CompletionUsage, context_limit: int | None = None) -> model.Usage:
    total_tokens = usage.total_tokens
    context_usage_percent = (total_tokens / context_limit) * 100 if context_limit else None
    return model.Usage(
        input_tokens=usage.prompt_tokens,
        cached_tokens=(usage.prompt_tokens_details.cached_tokens if usage.prompt_tokens_details else 0) or 0,
        reasoning_tokens=(usage.completion_tokens_details.reasoning_tokens if usage.completion_tokens_details else 0)
        or 0,
        output_tokens=usage.completion_tokens,
        total_tokens=total_tokens,
        context_usage_percent=context_usage_percent,
        throughput_tps=None,
        first_token_latency_ms=None,
    )
