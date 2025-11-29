from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, MutableMapping, Sequence
from dataclasses import dataclass

from klaude_code.core.tool.tool_abc import ToolABC
from klaude_code.core.tool.tool_context import TodoContext, tool_context
from klaude_code.core.tool.tool_runner import (
    ToolExecutionCallStarted,
    ToolExecutionResult,
    ToolExecutionTodoChange,
    ToolExecutor,
    ToolExecutorEvent,
)
from klaude_code.llm.client import LLMClientABC
from klaude_code.protocol import events, llm_parameter, model
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
    tools: list[llm_parameter.ToolSchema]
    tool_registry: dict[str, type[ToolABC]]
    # For tool context
    file_tracker: MutableMapping[str, float]
    todo_context: TodoContext


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

        turn_reasoning_items: list[model.ReasoningTextItem | model.ReasoningEncryptedItem] = []
        turn_assistant_message: model.AssistantMessageItem | None = None
        turn_tool_calls: list[model.ToolCallItem] = []
        response_failed = False
        error_message: str | None = None

        async for response_item in ctx.llm_client.call(
            llm_parameter.LLMCallParameter(
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
                    pass
                case model.ReasoningTextItem() as item:
                    turn_reasoning_items.append(item)
                    yield events.ThinkingEvent(
                        content=item.content,
                        response_id=item.response_id,
                        session_id=ctx.session_id,
                    )
                case model.ReasoningEncryptedItem() as item:
                    turn_reasoning_items.append(item)
                case model.AssistantMessageDelta() as item:
                    yield events.AssistantMessageDeltaEvent(
                        content=item.content,
                        response_id=item.response_id,
                        session_id=ctx.session_id,
                    )
                case model.AssistantMessageItem() as item:
                    turn_assistant_message = item
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
                    status = item.status
                    if status is not None and status != "completed":
                        response_failed = True
                        error_message = f"Response status: {status}"
                case model.StreamErrorItem() as item:
                    response_failed = True
                    error_message = item.error
                    log_debug(
                        "[StreamError]",
                        item.error,
                        style="red",
                        debug_type=DebugType.RESPONSE,
                    )
                case model.ToolCallItem() as item:
                    turn_tool_calls.append(item)
                case _:
                    pass

        if response_failed:
            yield events.TurnEndEvent(session_id=ctx.session_id)
            raise TurnError(error_message or "Turn failed")

        # Append to history only on success
        if turn_reasoning_items:
            ctx.append_history(turn_reasoning_items)
        if turn_assistant_message:
            ctx.append_history([turn_assistant_message])
        if turn_tool_calls:
            ctx.append_history(turn_tool_calls)
            self._has_tool_call = True

        # Execute tools
        if turn_tool_calls:
            with tool_context(ctx.file_tracker, ctx.todo_context):
                executor = ToolExecutor(
                    registry=ctx.tool_registry,
                    append_history=ctx.append_history,
                )
                self._tool_executor = executor

                async for exec_event in executor.run_tools(turn_tool_calls):
                    for ui_event in build_events_from_tool_executor_event(ctx.session_id, exec_event):
                        yield ui_event
                self._tool_executor = None

        yield events.TurnEndEvent(session_id=ctx.session_id)
