import json
from collections.abc import AsyncGenerator
from typing import Literal, override

import httpx
import openai

from klaude_code.llm.client import LLMClientABC, call_with_logged_payload
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.openai_compatible.input import convert_history_to_input, convert_tool_schema
from klaude_code.llm.openai_compatible.tool_call_accumulator import BasicToolCallAccumulator, ToolCallAccumulatorABC
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, convert_usage
from klaude_code.protocol import llm_param, model
from klaude_code.trace import DebugType, log_debug


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
    async def call(self, param: llm_param.LLMCallParameter) -> AsyncGenerator[model.ConversationItem, None]:
        param = apply_config_defaults(param, self.get_llm_config())
        messages = convert_history_to_input(param.input, param.system, param.model)
        tools = convert_tool_schema(param.tools)

        metadata_tracker = MetadataTracker(cost_config=self._config.cost)

        extra_body = {}
        extra_headers = {"extra": json.dumps({"session_id": param.session_id}, sort_keys=True)}

        if param.thinking:
            extra_body["thinking"] = {
                "type": param.thinking.type,
                "budget": param.thinking.budget_tokens,
            }
        stream = call_with_logged_payload(
            self.client.chat.completions.create,
            model=str(param.model),
            tool_choice="auto",
            parallel_tool_calls=True,
            stream=True,
            messages=messages,
            temperature=param.temperature,
            max_tokens=param.max_tokens,
            tools=tools,
            reasoning_effort=param.thinking.reasoning_effort if param.thinking else None,
            verbosity=param.verbosity,
            extra_body=extra_body,  # pyright: ignore[reportUnknownArgumentType]
            extra_headers=extra_headers,
        )

        stage: Literal["waiting", "reasoning", "assistant", "tool", "done"] = "waiting"
        accumulated_reasoning: list[str] = []
        accumulated_content: list[str] = []
        accumulated_tool_calls: ToolCallAccumulatorABC = BasicToolCallAccumulator()
        emitted_tool_start_indices: set[int] = set()
        response_id: str | None = None

        def flush_reasoning_items() -> list[model.ConversationItem]:
            nonlocal accumulated_reasoning
            if not accumulated_reasoning:
                return []
            item = model.ReasoningTextItem(
                content="".join(accumulated_reasoning),
                response_id=response_id,
                model=str(param.model),
            )
            accumulated_reasoning = []
            return [item]

        def flush_assistant_items() -> list[model.ConversationItem]:
            nonlocal accumulated_content
            if len(accumulated_content) == 0:
                return []
            item = model.AssistantMessageItem(
                content="".join(accumulated_content),
                response_id=response_id,
            )
            accumulated_content = []
            return [item]

        def flush_tool_call_items() -> list[model.ToolCallItem]:
            nonlocal accumulated_tool_calls
            items: list[model.ToolCallItem] = accumulated_tool_calls.get()
            if items:
                accumulated_tool_calls.chunks_by_step = []  # pyright: ignore[reportAttributeAccessIssue]
            return items

        try:
            async for event in await stream:
                log_debug(
                    event.model_dump_json(exclude_none=True),
                    style="blue",
                    debug_type=DebugType.LLM_STREAM,
                )
                if not response_id and event.id:
                    response_id = event.id
                    accumulated_tool_calls.response_id = response_id
                    yield model.StartItem(response_id=response_id)
                if (
                    event.usage is not None and event.usage.completion_tokens is not None  # pyright: ignore[reportUnnecessaryComparison] gcp gemini will return None usage field
                ):
                    metadata_tracker.set_usage(convert_usage(event.usage, param.context_limit))
                if event.model:
                    metadata_tracker.set_model_name(event.model)
                if provider := getattr(event, "provider", None):
                    metadata_tracker.set_provider(str(provider))

                if len(event.choices) == 0:
                    continue
                delta = event.choices[0].delta

                # Support Kimi K2's usage field in choice
                if hasattr(event.choices[0], "usage") and getattr(event.choices[0], "usage"):
                    metadata_tracker.set_usage(
                        convert_usage(
                            openai.types.CompletionUsage.model_validate(getattr(event.choices[0], "usage")),
                            param.context_limit,
                        )
                    )

                # Reasoning
                reasoning_content = ""
                if hasattr(delta, "reasoning") and getattr(delta, "reasoning"):
                    reasoning_content = getattr(delta, "reasoning")
                if hasattr(delta, "reasoning_content") and getattr(delta, "reasoning_content"):
                    reasoning_content = getattr(delta, "reasoning_content")
                if reasoning_content:
                    metadata_tracker.record_token()
                    stage = "reasoning"
                    accumulated_reasoning.append(reasoning_content)

                # Assistant
                if delta.content and (
                    stage == "assistant" or delta.content.strip()
                ):  # Process all content in assistant stage, filter empty content in reasoning stage
                    metadata_tracker.record_token()
                    if stage == "reasoning":
                        for item in flush_reasoning_items():
                            yield item
                    elif stage == "tool":
                        for item in flush_tool_call_items():
                            yield item
                    stage = "assistant"
                    accumulated_content.append(delta.content)
                    yield model.AssistantMessageDelta(
                        content=delta.content,
                        response_id=response_id,
                    )

                # Tool
                if delta.tool_calls and len(delta.tool_calls) > 0:
                    metadata_tracker.record_token()
                    if stage == "reasoning":
                        for item in flush_reasoning_items():
                            yield item
                    elif stage == "assistant":
                        for item in flush_assistant_items():
                            yield item
                    stage = "tool"
                    # Emit ToolCallStartItem for new tool calls
                    for tc in delta.tool_calls:
                        if tc.index not in emitted_tool_start_indices and tc.function and tc.function.name:
                            emitted_tool_start_indices.add(tc.index)
                            yield model.ToolCallStartItem(
                                response_id=response_id,
                                call_id=tc.id or "",
                                name=tc.function.name,
                            )
                    accumulated_tool_calls.add(delta.tool_calls)
        except (openai.OpenAIError, httpx.HTTPError) as e:
            yield model.StreamErrorItem(error=f"{e.__class__.__name__} {str(e)}")

        # Finalize
        for item in flush_reasoning_items():
            yield item

        for item in flush_assistant_items():
            yield item

        if stage == "tool":
            for tool_call_item in flush_tool_call_items():
                yield tool_call_item

        metadata_tracker.set_response_id(response_id)
        yield metadata_tracker.finalize()
