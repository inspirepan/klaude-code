from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from klaude_code.const import RETRY_PRESERVE_PARTIAL_MESSAGE, SUPPORTED_IMAGE_SIZES
from klaude_code.core.tool import ToolABC
from klaude_code.core.tool.context import SubAgentResumeClaims, ToolContext

if TYPE_CHECKING:
    from klaude_code.core.task import SessionContext

from klaude_code.core.tool.tool_runner import (
    ToolCallRequest,
    ToolExecutionCallStarted,
    ToolExecutionResult,
    ToolExecutionTodoChange,
    ToolExecutor,
    ToolExecutorEvent,
)
from klaude_code.llm import LLMClientABC
from klaude_code.llm.client import LLMStreamABC
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, llm_param, message, model, tools

# Protocols that support prefill (continuing from partial assistant message)
_PREFILL_SUPPORTED_PROTOCOLS = frozenset(
    {
        "anthropic",
        "claude_oauth",
    }
)


class TurnError(Exception):
    """Raised when a turn fails and should be retried."""

    pass


@dataclass
class TurnExecutionContext:
    """Execution context required to run a single turn."""

    session_ctx: SessionContext
    llm_client: LLMClientABC
    system_prompt: str | None
    tools: list[llm_param.ToolSchema]
    tool_registry: dict[str, type[ToolABC]]
    sub_agent_state: model.SubAgentState | None = None


@dataclass
class TurnResult:
    """Aggregated state produced while executing a turn."""

    assistant_message: message.AssistantMessage | None
    tool_calls: list[ToolCallRequest]
    stream_error: message.StreamErrorItem | None
    report_back_result: str | None = field(default=None)


def build_events_from_tool_executor_event(session_id: str, event: ToolExecutorEvent) -> list[events.Event]:
    """Translate internal tool executor events into public protocol events."""

    ui_events: list[events.Event] = []

    match event:
        case ToolExecutionCallStarted(tool_call=tool_call):
            ui_events.append(
                events.ToolCallEvent(
                    session_id=session_id,
                    response_id=tool_call.response_id,
                    tool_call_id=tool_call.call_id,
                    tool_name=tool_call.tool_name,
                    arguments=tool_call.arguments_json,
                )
            )
        case ToolExecutionResult(tool_call=tool_call, tool_result=tool_result, is_last_in_turn=is_last_in_turn):
            ui_events.append(
                events.ToolResultEvent(
                    session_id=session_id,
                    response_id=tool_call.response_id,
                    tool_call_id=tool_call.call_id,
                    tool_name=tool_call.tool_name,
                    result=tool_result.output_text,
                    ui_extra=tool_result.ui_extra,
                    status=tool_result.status,
                    task_metadata=tool_result.task_metadata,
                    is_last_in_turn=is_last_in_turn,
                )
            )
        case ToolExecutionTodoChange(todos=todos):
            ui_events.append(
                events.TodoChangeEvent(
                    session_id=session_id,
                    todos=todos,
                )
            )

    return ui_events


class TurnExecutor:
    """Executes a single model turn including tool calls.

    Manages the lifecycle of tool execution and tool context internally.
    Raises TurnError on failure.
    """

    def __init__(self, context: TurnExecutionContext) -> None:
        self._context = context
        self._tool_executor: ToolExecutor | None = None
        self._turn_result: TurnResult | None = None
        self._llm_stream: LLMStreamABC | None = None

    @property
    def report_back_result(self) -> str | None:
        return self._turn_result.report_back_result if self._turn_result else None

    @property
    def task_finished(self) -> bool:
        """Check if this turn indicates the task should end.

        Task ends when there are no tool calls or report_back was called.
        """
        if self._turn_result is None:
            return True
        if not self._turn_result.tool_calls:
            return True
        return self._turn_result.report_back_result is not None

    @property
    def task_result(self) -> str:
        """Get the task result from this turn.

        Returns report_back result if available, otherwise returns
        the assistant message content.
        """
        if self._turn_result is not None and self._turn_result.report_back_result is not None:
            return self._turn_result.report_back_result
        if self._turn_result is not None and self._turn_result.assistant_message is not None:
            assistant_message = self._turn_result.assistant_message
            text = message.join_text_parts(assistant_message.parts)
            images = [part for part in assistant_message.parts if isinstance(part, message.ImageFilePart)]
            return message.format_saved_images(images, text)
        return ""

    @property
    def has_structured_output(self) -> bool:
        """Check if the task result is structured output from report_back."""
        return bool(self._turn_result and self._turn_result.report_back_result)

    def cancel(self) -> list[events.Event]:
        """Cancel running tools and return any resulting events."""
        ui_events: list[events.Event] = []
        self._persist_partial_message_on_cancel()
        if self._tool_executor is not None:
            for exec_event in self._tool_executor.cancel():
                for ui_event in build_events_from_tool_executor_event(self._context.session_ctx.session_id, exec_event):
                    ui_events.append(ui_event)
            self._tool_executor = None
        return ui_events

    async def run(self) -> AsyncGenerator[events.Event]:
        """Execute the turn, yielding events as they occur.

        Raises:
            TurnError: If the turn fails (stream error or non-completed status).
        """
        ctx = self._context
        session_ctx = ctx.session_ctx

        yield events.TurnStartEvent(session_id=session_ctx.session_id)

        self._turn_result = TurnResult(
            assistant_message=None,
            tool_calls=[],
            stream_error=None,
        )

        async for event in self._consume_llm_stream(self._turn_result):
            yield event

        if self._turn_result.stream_error is not None:
            # Save accumulated content for potential prefill on retry (only for supported protocols)
            session_ctx.append_history([self._turn_result.stream_error])
            protocol = ctx.llm_client.get_llm_config().protocol
            supports_prefill = protocol.value in _PREFILL_SUPPORTED_PROTOCOLS
            if (
                RETRY_PRESERVE_PARTIAL_MESSAGE
                and supports_prefill
                and self._turn_result.assistant_message is not None
                and self._turn_result.assistant_message.parts
            ):
                # Discard partial message if it only contains thinking parts
                has_non_thinking = any(
                    not isinstance(part, message.ThinkingTextPart)
                    for part in self._turn_result.assistant_message.parts
                )
                if has_non_thinking:
                    session_ctx.append_history([self._turn_result.assistant_message])
                    # Add continuation prompt to avoid Anthropic thinking block requirement
                    session_ctx.append_history(
                        [message.UserMessage(parts=[message.TextPart(text="<system>continue</system>")])]
                    )
            yield events.TurnEndEvent(session_id=session_ctx.session_id)
            raise TurnError(self._turn_result.stream_error.error)

        self._append_success_history(self._turn_result)

        if self._turn_result.tool_calls:
            # Check for report_back before running tools
            self._detect_report_back(self._turn_result)

            async for ui_event in self._run_tool_executor(self._turn_result.tool_calls):
                yield ui_event

        yield events.TurnEndEvent(session_id=session_ctx.session_id)

    def _detect_report_back(self, turn_result: TurnResult) -> None:
        """Detect report_back tool call and store its arguments as JSON string."""
        for tool_call in turn_result.tool_calls:
            if tool_call.tool_name == tools.REPORT_BACK:
                turn_result.report_back_result = tool_call.arguments_json
                break

    async def _consume_llm_stream(self, turn_result: TurnResult) -> AsyncGenerator[events.Event]:
        """Stream events from LLM and update turn_result in place."""

        ctx = self._context
        session_ctx = ctx.session_ctx
        thinking_active = False
        assistant_text_active = False
        message_types = (
            message.SystemMessage,
            message.DeveloperMessage,
            message.UserMessage,
            message.AssistantMessage,
            message.ToolResultMessage,
        )
        messages = [item for item in session_ctx.get_conversation_history() if isinstance(item, message_types)]
        call_param = llm_param.LLMCallParameter(
            input=messages,
            system=ctx.system_prompt,
            tools=ctx.tools,
            session_id=session_ctx.session_id,
        )

        # ImageGen per-call overrides (tool-level `generation` parameters)
        if ctx.sub_agent_state is not None and ctx.sub_agent_state.sub_agent_type == tools.IMAGE_GEN:
            call_param.modalities = ["image", "text"]
            generation = ctx.sub_agent_state.generation or {}
            image_config = llm_param.ImageConfig()
            aspect_ratio = generation.get("aspect_ratio")
            if isinstance(aspect_ratio, str) and aspect_ratio.strip():
                image_config.aspect_ratio = aspect_ratio.strip()
            image_size = generation.get("image_size")
            if image_size in SUPPORTED_IMAGE_SIZES:
                image_config.image_size = image_size
            if image_config.model_dump(exclude_none=True):
                call_param.image_config = image_config

        self._llm_stream = await ctx.llm_client.call(call_param)
        try:
            async for delta in self._llm_stream:
                log_debug(
                    f"[{delta.__class__.__name__}]",
                    delta.model_dump_json(exclude_none=True),
                    style="green",
                    debug_type=DebugType.RESPONSE,
                )
                match delta:
                    case message.ThinkingTextDelta() as delta:
                        if not thinking_active:
                            thinking_active = True
                            yield events.ThinkingStartEvent(
                                response_id=delta.response_id,
                                session_id=session_ctx.session_id,
                            )
                        yield events.ThinkingDeltaEvent(
                            content=delta.content,
                            response_id=delta.response_id,
                            session_id=session_ctx.session_id,
                        )
                    case message.AssistantTextDelta() as delta:
                        if thinking_active:
                            thinking_active = False
                            yield events.ThinkingEndEvent(
                                response_id=delta.response_id,
                                session_id=session_ctx.session_id,
                            )
                        if not assistant_text_active:
                            assistant_text_active = True
                            yield events.AssistantTextStartEvent(
                                response_id=delta.response_id,
                                session_id=session_ctx.session_id,
                            )
                        yield events.AssistantTextDeltaEvent(
                            content=delta.content,
                            response_id=delta.response_id,
                            session_id=session_ctx.session_id,
                        )
                    case message.AssistantImageDelta() as delta:
                        if thinking_active:
                            thinking_active = False
                            yield events.ThinkingEndEvent(
                                response_id=delta.response_id,
                                session_id=session_ctx.session_id,
                            )
                        yield events.AssistantImageDeltaEvent(
                            file_path=delta.file_path,
                            response_id=delta.response_id,
                            session_id=session_ctx.session_id,
                        )
                    case message.AssistantMessage() as msg:
                        if thinking_active:
                            thinking_active = False
                            yield events.ThinkingEndEvent(
                                response_id=msg.response_id,
                                session_id=session_ctx.session_id,
                            )
                        if assistant_text_active:
                            assistant_text_active = False
                            yield events.AssistantTextEndEvent(
                                response_id=msg.response_id,
                                session_id=session_ctx.session_id,
                            )
                        turn_result.assistant_message = msg
                        for part in msg.parts:
                            if isinstance(part, message.ToolCallPart):
                                turn_result.tool_calls.append(
                                    ToolCallRequest(
                                        response_id=msg.response_id,
                                        call_id=part.call_id,
                                        tool_name=part.tool_name,
                                        arguments_json=part.arguments_json,
                                    )
                                )
                        if msg.stop_reason != "aborted":
                            thinking_text = "".join(
                                part.text for part in msg.parts if isinstance(part, message.ThinkingTextPart)
                            )
                            yield events.ResponseCompleteEvent(
                                content=message.join_text_parts(msg.parts),
                                response_id=msg.response_id,
                                session_id=session_ctx.session_id,
                                thinking_text=thinking_text or None,
                            )
                        if msg.stop_reason == "aborted":
                            yield events.InterruptEvent(session_id=session_ctx.session_id)
                        if msg.usage:
                            metadata = msg.usage
                            if metadata.response_id is None:
                                metadata.response_id = msg.response_id
                            if not metadata.model_name:
                                metadata.model_name = ctx.llm_client.model_name
                            if metadata.provider is None:
                                metadata.provider = ctx.llm_client.get_llm_config().provider_name or None
                            yield events.UsageEvent(
                                session_id=session_ctx.session_id,
                                usage=metadata,
                            )
                    case message.StreamErrorItem() as msg:
                        turn_result.stream_error = msg
                    case message.ToolCallStartDelta() as msg:
                        if thinking_active:
                            thinking_active = False
                            yield events.ThinkingEndEvent(
                                response_id=msg.response_id,
                                session_id=session_ctx.session_id,
                            )
                        if assistant_text_active:
                            assistant_text_active = False
                            yield events.AssistantTextEndEvent(
                                response_id=msg.response_id,
                                session_id=session_ctx.session_id,
                            )
                        yield events.ToolCallStartEvent(
                            session_id=session_ctx.session_id,
                            response_id=msg.response_id,
                            tool_call_id=msg.call_id,
                            tool_name=msg.name,
                        )
                    case _:
                        continue
        finally:
            self._llm_stream = None

    def _append_success_history(self, turn_result: TurnResult) -> None:
        """Persist successful turn artifacts to conversation history."""
        session_ctx = self._context.session_ctx
        if turn_result.assistant_message:
            session_ctx.append_history([turn_result.assistant_message])

    async def _run_tool_executor(self, tool_calls: list[ToolCallRequest]) -> AsyncGenerator[events.Event]:
        """Run tools for the turn and translate executor events to UI events."""

        ctx = self._context
        session_ctx = ctx.session_ctx
        tool_context = ToolContext(
            file_tracker=session_ctx.file_tracker,
            todo_context=session_ctx.todo_context,
            session_id=session_ctx.session_id,
            run_subtask=session_ctx.run_subtask,
            sub_agent_resume_claims=SubAgentResumeClaims(),
        )

        executor = ToolExecutor(
            context=tool_context,
            registry=ctx.tool_registry,
            append_history=session_ctx.append_history,
        )
        self._tool_executor = executor
        try:
            async for exec_event in executor.run_tools(tool_calls):
                for ui_event in build_events_from_tool_executor_event(session_ctx.session_id, exec_event):
                    yield ui_event
        finally:
            self._tool_executor = None

    def _persist_partial_message_on_cancel(self) -> None:
        """Persist accumulated message when a turn is interrupted.

        Retrieves the partial message from the LLM stream, including both
        thinking and assistant text accumulated so far.
        """
        if self._llm_stream is None:
            return
        partial_message = self._llm_stream.get_partial_message()
        if partial_message is None:
            return
        self._context.session_ctx.append_history([partial_message])
