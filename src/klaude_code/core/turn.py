from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, MutableMapping, Sequence
from dataclasses import dataclass

from klaude_code.core.tool import TodoContext, ToolABC, tool_context
from klaude_code.core.tool.tool_runner import (
    ToolExecutionCallStarted,
    ToolExecutionResult,
    ToolExecutionTodoChange,
    ToolExecutor,
    ToolExecutorEvent,
)
from klaude_code.llm import LLMClientABC
from klaude_code.protocol import events, llm_param, model
from klaude_code.trace import DebugType, log_debug


class TurnError(Exception):
    """Raised when a turn fails and should be retried."""

    pass


@dataclass
class TurnExecutionContext:
    """Execution context required to run a single turn."""

    session_id: str
    get_conversation_history: Callable[[], list[model.ConversationItem]]
    append_history: Callable[[Sequence[model.ConversationItem]], None]
    llm_client: LLMClientABC
    system_prompt: str | None
    tools: list[llm_param.ToolSchema]
    tool_registry: dict[str, type[ToolABC]]
    # For tool context
    file_tracker: MutableMapping[str, float]
    todo_context: TodoContext


@dataclass
class TurnResult:
    """Aggregated state produced while executing a turn."""

    reasoning_items: list[model.ReasoningTextItem | model.ReasoningEncryptedItem]
    assistant_message: model.AssistantMessageItem | None
    tool_calls: list[model.ToolCallItem]
    stream_error: model.StreamErrorItem | None


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
        self._has_tool_call: bool = False

    @property
    def has_tool_call(self) -> bool:
        return self._has_tool_call

    def cancel(self) -> list[events.Event]:
        """Cancel running tools and return any resulting events."""
        ui_events: list[events.Event] = []
        if self._tool_executor is not None:
            for exec_event in self._tool_executor.cancel():
                for ui_event in build_events_from_tool_executor_event(self._context.session_id, exec_event):
                    ui_events.append(ui_event)
            self._tool_executor = None
        return ui_events

    async def run(self) -> AsyncGenerator[events.Event, None]:
        """Execute the turn, yielding events as they occur.

        Raises:
            TurnError: If the turn fails (stream error or non-completed status).
        """
        ctx = self._context

        yield events.TurnStartEvent(session_id=ctx.session_id)

        turn_result = TurnResult(
            reasoning_items=[],
            assistant_message=None,
            tool_calls=[],
            stream_error=None,
        )

        async for event in self._consume_llm_stream(turn_result):
            yield event

        if turn_result.stream_error is not None:
            ctx.append_history([turn_result.stream_error])
            yield events.TurnEndEvent(session_id=ctx.session_id)
            raise TurnError(turn_result.stream_error.error)

        self._append_success_history(turn_result)
        self._has_tool_call = bool(turn_result.tool_calls)

        if turn_result.tool_calls:
            async for ui_event in self._run_tool_executor(turn_result.tool_calls):
                yield ui_event

        yield events.TurnEndEvent(session_id=ctx.session_id)

    async def _consume_llm_stream(self, turn_result: TurnResult) -> AsyncGenerator[events.Event, None]:
        """Stream events from LLM and update turn_result in place."""

        ctx = self._context
        async for response_item in ctx.llm_client.call(
            llm_param.LLMCallParameter(
                input=ctx.get_conversation_history(),
                system=ctx.system_prompt,
                tools=ctx.tools,
                store=False,
                session_id=ctx.session_id,
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
                        session_id=ctx.session_id,
                    )
                case model.ReasoningEncryptedItem() as item:
                    turn_result.reasoning_items.append(item)
                case model.AssistantMessageDelta() as item:
                    yield events.AssistantMessageDeltaEvent(
                        content=item.content,
                        response_id=item.response_id,
                        session_id=ctx.session_id,
                    )
                case model.AssistantMessageItem() as item:
                    turn_result.assistant_message = item
                    yield events.AssistantMessageEvent(
                        content=item.content or "",
                        response_id=item.response_id,
                        session_id=ctx.session_id,
                    )
                case model.ResponseMetadataItem() as item:
                    yield events.ResponseMetadataEvent(
                        session_id=ctx.session_id,
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
                        session_id=ctx.session_id,
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
        ctx = self._context
        if turn_result.reasoning_items:
            ctx.append_history(turn_result.reasoning_items)
        if turn_result.assistant_message:
            ctx.append_history([turn_result.assistant_message])
        if turn_result.tool_calls:
            ctx.append_history(turn_result.tool_calls)

    async def _run_tool_executor(self, tool_calls: list[model.ToolCallItem]) -> AsyncGenerator[events.Event, None]:
        """Run tools for the turn and translate executor events to UI events."""

        ctx = self._context
        with tool_context(ctx.file_tracker, ctx.todo_context):
            executor = ToolExecutor(
                registry=ctx.tool_registry,
                append_history=ctx.append_history,
            )
            self._tool_executor = executor
            try:
                async for exec_event in executor.run_tools(tool_calls):
                    for ui_event in build_events_from_tool_executor_event(ctx.session_id, exec_event):
                        yield ui_event
            finally:
                self._tool_executor = None
