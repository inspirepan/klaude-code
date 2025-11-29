import time
from collections.abc import AsyncGenerator
from enum import Enum
from typing import Literal, override

import httpx
import openai
from pydantic import BaseModel

from klaude_code.llm.client import LLMClientABC, call_with_logged_payload
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.openai_compatible.input import convert_tool_schema
from klaude_code.llm.openai_compatible.tool_call_accumulator import BasicToolCallAccumulator, ToolCallAccumulatorABC
from klaude_code.llm.openrouter.input import convert_history_to_input, is_claude_model
from klaude_code.llm.registry import register
from klaude_code.protocol import llm_param, model
from klaude_code.trace import DebugType, log, log_debug


class ReasoningDetail(BaseModel):
    """OpenRouter's https://openrouter.ai/docs/use-cases/reasoning-tokens#reasoning_details-array-structure"""

    type: str
    format: str
    index: int
    id: str | None = None
    data: str | None = None  # OpenAI's encrypted content
    summary: str | None = None
    text: str | None = None
    signature: str | None = None  # Claude's signature


class ReasoningMode(str, Enum):
    COMPLETE_CHUNK = "complete_chunk"
    GPT5_SECTIONS = "gpt5_sections"
    ACCUMULATE = "accumulate"


class ReasoningStreamHandler:
    """Encapsulates reasoning stream handling across different model behaviors."""

    def __init__(
        self,
        param_model: str,
        response_id: str | None,
    ) -> None:
        self._param_model = param_model
        self._response_id = response_id

        self._reasoning_id: str | None = None
        self._accumulated_reasoning: list[str] = []
        self._gpt5_line_buffer: str = ""
        self._gpt5_section_lines: list[str] = []

    def set_response_id(self, response_id: str | None) -> None:
        """Update the response identifier used for emitted items."""

        self._response_id = response_id

    def on_detail(self, detail: ReasoningDetail) -> list[model.ConversationItem]:
        """Process a single reasoning detail and return streamable items."""

        items: list[model.ConversationItem] = []

        if detail.type == "reasoning.encrypted":
            self._reasoning_id = detail.id
            if encrypted_item := self._build_encrypted_item(detail.data, detail):
                items.append(encrypted_item)
            return items

        if detail.type in ("reasoning.text", "reasoning.summary"):
            self._reasoning_id = detail.id
            if encrypted_item := self._build_encrypted_item(detail.signature, detail):
                items.append(encrypted_item)
            text = detail.text if detail.type == "reasoning.text" else detail.summary
            if text:
                items.extend(self._handle_text(text))

        return items

    def flush(self) -> list[model.ConversationItem]:
        """Flush buffered reasoning text and encrypted payloads."""

        items: list[model.ConversationItem] = []
        mode = self._resolve_mode()

        if mode is ReasoningMode.GPT5_SECTIONS:
            for section in self._drain_gpt5_sections():
                items.append(self._build_text_item(section))
        elif self._accumulated_reasoning and mode is ReasoningMode.ACCUMULATE:
            items.append(self._build_text_item("".join(self._accumulated_reasoning)))
            self._accumulated_reasoning = []

        return items

    def _handle_text(self, text: str) -> list[model.ReasoningTextItem]:
        mode = self._resolve_mode()
        if mode is ReasoningMode.COMPLETE_CHUNK:
            return [self._build_text_item(text)]
        if mode is ReasoningMode.GPT5_SECTIONS:
            sections = self._process_gpt5_text(text)
            return [self._build_text_item(section) for section in sections]
        self._accumulated_reasoning.append(text)
        return []

    def _build_text_item(self, content: str) -> model.ReasoningTextItem:
        return model.ReasoningTextItem(
            id=self._reasoning_id,
            content=content,
            response_id=self._response_id,
            model=self._param_model,
        )

    def _build_encrypted_item(
        self,
        content: str | None,
        detail: ReasoningDetail,
    ) -> model.ReasoningEncryptedItem | None:
        if not content:
            return None
        return model.ReasoningEncryptedItem(
            id=detail.id,
            encrypted_content=content,
            format=detail.format,
            response_id=self._response_id,
            model=self._param_model,
        )

    def _process_gpt5_text(self, text: str) -> list[str]:
        emitted_sections: list[str] = []
        self._gpt5_line_buffer += text
        while True:
            newline_index = self._gpt5_line_buffer.find("\n")
            if newline_index == -1:
                break
            line = self._gpt5_line_buffer[:newline_index]
            self._gpt5_line_buffer = self._gpt5_line_buffer[newline_index + 1 :]
            remainder = line
            while True:
                split_result = self._split_gpt5_title_line(remainder)
                if split_result is None:
                    break
                prefix_segment, title_segment, remainder = split_result
                if prefix_segment:
                    if not self._gpt5_section_lines:
                        self._gpt5_section_lines = []
                    self._gpt5_section_lines.append(f"{prefix_segment}\n")
                if self._gpt5_section_lines:
                    emitted_sections.append("".join(self._gpt5_section_lines))
                self._gpt5_section_lines = [f"{title_segment}  \n"]  # Add two spaces for markdown line break
            if remainder:
                if not self._gpt5_section_lines:
                    self._gpt5_section_lines = []
                self._gpt5_section_lines.append(f"{remainder}\n")
        return emitted_sections

    def _drain_gpt5_sections(self) -> list[str]:
        sections: list[str] = []
        if self._gpt5_line_buffer:
            if not self._gpt5_section_lines:
                self._gpt5_section_lines = [self._gpt5_line_buffer]
            else:
                self._gpt5_section_lines.append(self._gpt5_line_buffer)
            self._gpt5_line_buffer = ""
        if self._gpt5_section_lines:
            sections.append("".join(self._gpt5_section_lines))
            self._gpt5_section_lines = []
        return sections

    def _is_gpt5(self) -> bool:
        return "gpt-5" in self._param_model.lower()

    def _is_complete_chunk_reasoning_model(self) -> bool:
        """Whether the current model emits reasoning in complete chunks (e.g. Gemini)."""

        return self._param_model.startswith("google/gemini")

    def _resolve_mode(self) -> ReasoningMode:
        if self._is_complete_chunk_reasoning_model():
            return ReasoningMode.COMPLETE_CHUNK
        if self._is_gpt5():
            return ReasoningMode.GPT5_SECTIONS
        return ReasoningMode.ACCUMULATE

    def _is_gpt5_title_line(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        return stripped.startswith("**") and stripped.endswith("**") and stripped.count("**") >= 2

    def _split_gpt5_title_line(self, line: str) -> tuple[str | None, str, str] | None:
        if not line:
            return None
        search_start = 0
        while True:
            opening_index = line.find("**", search_start)
            if opening_index == -1:
                return None
            closing_index = line.find("**", opening_index + 2)
            if closing_index == -1:
                return None
            title_candidate = line[opening_index : closing_index + 2]
            stripped_title = title_candidate.strip()
            if self._is_gpt5_title_line(stripped_title):
                # Treat as a GPT-5 title only when everything after the
                # bold segment is either whitespace or starts a new bold
                # title. This prevents inline bold like `**xxx**yyyy`
                # from being misclassified as a section title while
                # preserving support for consecutive titles in one line.
                after = line[closing_index + 2 :]
                if after.strip() and not after.lstrip().startswith("**"):
                    search_start = closing_index + 2
                    continue
                prefix_segment = line[:opening_index]
                remainder_segment = after
                return (
                    prefix_segment if prefix_segment else None,
                    stripped_title,
                    remainder_segment,
                )
            search_start = closing_index + 2


@register(llm_param.LLMClientProtocol.OPENROUTER)
class OpenRouterClient(LLMClientABC):
    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        client = openai.AsyncOpenAI(
            api_key=config.api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=httpx.Timeout(300.0, connect=15.0, read=285.0),
        )
        self.client: openai.AsyncOpenAI = client

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> AsyncGenerator[model.ConversationItem, None]:
        param = apply_config_defaults(param, self.get_llm_config())
        messages = convert_history_to_input(param.input, param.system, param.model)
        tools = convert_tool_schema(param.tools)

        request_start_time = time.time()
        first_token_time: float | None = None
        last_token_time: float | None = None

        extra_body: dict[str, object] = {
            "usage": {"include": True}  # To get the cache tokens at the end of the response
        }
        extra_headers = {}

        if param.thinking:
            if param.thinking.budget_tokens is not None:
                extra_body["reasoning"] = {
                    "max_tokens": param.thinking.budget_tokens,
                    "enable": True,
                }  # OpenRouter: https://openrouter.ai/docs/use-cases/reasoning-tokens#anthropic-models-with-reasoning-tokens
            elif param.thinking.reasoning_effort is not None:
                extra_body["reasoning"] = {
                    "effort": param.thinking.reasoning_effort,
                }
        if param.provider_routing:
            extra_body["provider"] = param.provider_routing.model_dump(exclude_none=True)
        if is_claude_model(param.model):
            extra_headers["anthropic-beta"] = (
                "interleaved-thinking-2025-05-14"  # Not working yet, maybe OpenRouter's issue, or Anthropic: Interleaved thinking is only supported for tools used via the Messages API.
            )

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
            verbosity=param.verbosity,
            extra_body=extra_body,  # pyright: ignore[reportUnknownArgumentType]
            extra_headers=extra_headers,  # pyright: ignore[reportUnknownArgumentType]
        )

        stage: Literal["waiting", "reasoning", "assistant", "tool", "done"] = "waiting"
        response_id: str | None = None
        accumulated_content: list[str] = []
        accumulated_tool_calls: ToolCallAccumulatorABC = BasicToolCallAccumulator()
        metadata_item = model.ResponseMetadataItem()
        reasoning_handler = ReasoningStreamHandler(
            param_model=str(param.model),
            response_id=response_id,
        )

        def flush_reasoning_items() -> list[model.ConversationItem]:
            return reasoning_handler.flush()

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
                    reasoning_handler.set_response_id(response_id)
                    accumulated_tool_calls.response_id = response_id
                    yield model.StartItem(response_id=response_id)
                if (
                    event.usage is not None and event.usage.completion_tokens is not None  # pyright: ignore[reportUnnecessaryComparison]
                ):  # gcp gemini will return None usage field
                    metadata_item.usage = convert_usage(event.usage, param.context_limit)
                if event.model:
                    metadata_item.model_name = event.model
                if provider := getattr(event, "provider", None):
                    metadata_item.provider = str(provider)

                if len(event.choices) == 0:
                    continue
                delta = event.choices[0].delta

                # Reasoning
                if hasattr(delta, "reasoning_details") and getattr(delta, "reasoning_details"):
                    reasoning_details = getattr(delta, "reasoning_details")
                    for item in reasoning_details:
                        try:
                            reasoning_detail = ReasoningDetail.model_validate(item)
                            if first_token_time is None:
                                first_token_time = time.time()
                            last_token_time = time.time()
                            stage = "reasoning"
                            for conversation_item in reasoning_handler.on_detail(reasoning_detail):
                                yield conversation_item
                        except Exception as e:
                            log("reasoning_details error", str(e), style="red")

                # Assistant
                if delta.content and (
                    stage == "assistant" or delta.content.strip()
                ):  # Process all content in assistant stage, filter empty content in reasoning stage
                    if first_token_time is None:
                        first_token_time = time.time()
                    last_token_time = time.time()
                    if stage == "reasoning":
                        for item in flush_reasoning_items():
                            yield item
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
                        for item in flush_reasoning_items():
                            yield item
                    elif stage == "assistant":
                        for item in flush_assistant_items():
                            yield item
                    stage = "tool"
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
