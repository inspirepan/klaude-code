from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from klaude_code.core.tool import ToolABC, tool_context

if TYPE_CHECKING:
    from klaude_code.core.task import SessionContext

from klaude_code.core.tool.tool_runner import (
    ToolExecutionCallStarted,
    ToolExecutionResult,
    ToolExecutionTodoChange,
    ToolExecutor,
    ToolExecutorEvent,
)
from klaude_code.llm import LLMClientABC
from klaude_code.protocol import events, llm_param, model, tools
from klaude_code.trace import DebugType, log_debug


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


@dataclass
class TurnResult:
    """Aggregated state produced while executing a turn."""

    reasoning_items: list[model.ReasoningTextItem | model.ReasoningEncryptedItem]
    assistant_message: model.AssistantMessageItem | None
    tool_calls: list[model.ToolCallItem]
    stream_error: model.StreamErrorItem | None
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
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                )
            )
        case ToolExecutionResult(tool_call=tool_call, tool_result=tool_result):
            ui_events.append(
                events.ToolResultEvent(
                    session_id=session_id,
                    response_id=tool_call.response_id,
                    tool_call_id=tool_call.call_id,
                    tool_name=tool_call.name,
                    result=tool_result.output or "",
                    ui_extra=tool_result.ui_extra,
                    status=tool_result.status,
                    task_metadata=tool_result.task_metadata,
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
        self._assistant_delta_buffer: list[str] = []
        self._assistant_response_id: str | None = None

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
            return self._turn_result.assistant_message.content or ""
        return ""

    @property
    def has_structured_output(self) -> bool:
        """Check if the task result is structured output from report_back."""
        return bool(self._turn_result and self._turn_result.report_back_result)

    def cancel(self) -> list[events.Event]:
        """Cancel running tools and return any resulting events."""
        ui_events: list[events.Event] = []
        self._persist_partial_assistant_on_cancel()
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
            reasoning_items=[],
            assistant_message=None,
            tool_calls=[],
            stream_error=None,
        )

        async for event in self._consume_llm_stream(self._turn_result):
            yield event

        if self._turn_result.stream_error is not None:
            session_ctx.append_history([self._turn_result.stream_error])
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
            if tool_call.name == tools.REPORT_BACK:
                turn_result.report_back_result = tool_call.arguments
                break

    async def _consume_llm_stream(self, turn_result: TurnResult) -> AsyncGenerator[events.Event]:
        """Stream events from LLM and update turn_result in place."""

        ctx = self._context
        session_ctx = ctx.session_ctx
        async for response_item in ctx.llm_client.call(
            llm_param.LLMCallParameter(
                input=session_ctx.get_conversation_history(),
                system=ctx.system_prompt,
                tools=ctx.tools,
                session_id=session_ctx.session_id,
            )
        ):
            log_debug(
                f"[{response_item.__class__.__name__}]",
                response_item.model_dump_json(exclude_none=True),
                style="green",
                debug_type=DebugType.RESPONSE,
            )
            match response_item:
                case model.StartItem():
                    continue
                case model.ReasoningTextItem() as item:
                    turn_result.reasoning_items.append(item)
                    yield events.ThinkingEvent(
                        content=item.content,
                        response_id=item.response_id,
                        session_id=session_ctx.session_id,
                    )
                case model.ReasoningEncryptedItem() as item:
                    turn_result.reasoning_items.append(item)
                case model.ReasoningTextDelta() as item:
                    yield events.ThinkingDeltaEvent(
                        content=item.content,
                        response_id=item.response_id,
                        session_id=session_ctx.session_id,
                    )
                case model.AssistantMessageDelta() as item:
                    if item.response_id:
                        self._assistant_response_id = item.response_id
                    self._assistant_delta_buffer.append(item.content)
                    yield events.AssistantMessageDeltaEvent(
                        content=item.content,
                        response_id=item.response_id,
                        session_id=session_ctx.session_id,
                    )
                case model.AssistantMessageItem() as item:
                    turn_result.assistant_message = item
                    yield events.AssistantMessageEvent(
                        content=item.content or "",
                        response_id=item.response_id,
                        session_id=session_ctx.session_id,
                    )
                case model.ResponseMetadataItem() as item:
                    yield events.ResponseMetadataEvent(
                        session_id=session_ctx.session_id,
                        metadata=item,
                    )
                case model.StreamErrorItem() as item:
                    turn_result.stream_error = item
                    log_debug(
                        "[StreamError]",
                        item.error,
                        style="red",
                        debug_type=DebugType.RESPONSE,
                    )
                case model.ToolCallStartItem() as item:
                    yield events.TurnToolCallStartEvent(
                        session_id=session_ctx.session_id,
                        response_id=item.response_id,
                        tool_call_id=item.call_id,
                        tool_name=item.name,
                        arguments="",
                    )
                case model.ToolCallItem() as item:
                    turn_result.tool_calls.append(item)
                case _:
                    continue

    def _append_success_history(self, turn_result: TurnResult) -> None:
        """Persist successful turn artifacts to conversation history."""
        session_ctx = self._context.session_ctx
        if turn_result.reasoning_items:
            session_ctx.append_history(turn_result.reasoning_items)
        if turn_result.assistant_message:
            session_ctx.append_history([turn_result.assistant_message])
        if turn_result.tool_calls:
            session_ctx.append_history(turn_result.tool_calls)
        self._assistant_delta_buffer.clear()
        self._assistant_response_id = None

    async def _run_tool_executor(self, tool_calls: list[model.ToolCallItem]) -> AsyncGenerator[events.Event]:
        """Run tools for the turn and translate executor events to UI events."""

        ctx = self._context
        session_ctx = ctx.session_ctx
        with tool_context(session_ctx.file_tracker, session_ctx.todo_context):
            executor = ToolExecutor(
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

    def _persist_partial_assistant_on_cancel(self) -> None:
        """Persist streamed assistant text when a turn is interrupted.

        Reasoning and tool calls are intentionally discarded on interrupt; only
        the assistant message text collected so far is saved so it appears in
        subsequent history/context.
        """

        if not self._assistant_delta_buffer:
            return
        partial_text = "".join(self._assistant_delta_buffer) + "<system interrupted by user>"
        if not partial_text:
            return
        message_item = model.AssistantMessageItem(
            content=partial_text,
            response_id=self._assistant_response_id,
        )
        self._context.session_ctx.append_history([message_item])
        self._assistant_delta_buffer.clear()
