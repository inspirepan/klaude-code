import asyncio
import time
from collections.abc import AsyncGenerator, Callable, Iterable, Sequence
from dataclasses import dataclass

from klaude_code.prompts.messages import CANCEL_OUTPUT
from klaude_code.protocol import message
from klaude_code.protocol.models import SessionIdUIExtra, TaskMetadata, TodoItem, TodoListUIExtra, ToolSideEffect
from klaude_code.tool.core.abc import ToolABC, ToolConcurrencyPolicy
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.core.offload import offload_tool_output

LONG_RUNNING_TOOL_THRESHOLD_SECONDS = 5 * 60


@dataclass(frozen=True)
class ToolCallRequest:
    response_id: str | None
    call_id: str
    tool_name: str
    arguments_json: str


async def run_tool(
    tool_call: ToolCallRequest,
    registry: dict[str, type[ToolABC]],
    context: ToolContext,
) -> message.ToolResultMessage:
    """Execute a tool call and return the result.

    Args:
        tool_call: The tool call to execute.
        registry: The tool registry mapping tool names to tool classes.
        context: The explicit tool execution context.

    Returns:
        The result of the tool execution.
    """
    if tool_call.tool_name not in registry:
        return message.ToolResultMessage(
            call_id=tool_call.call_id,
            output_text=f"Tool {tool_call.tool_name} not exists",
            status="error",
            tool_name=tool_call.tool_name,
        )
    try:
        tool_result = await registry[tool_call.tool_name].call(tool_call.arguments_json, context)
        tool_result.call_id = tool_call.call_id
        tool_result.tool_name = tool_call.tool_name
        if tool_result.output_text:
            offload_result = offload_tool_output(tool_result.output_text, tool_call)
            tool_result.output_text = offload_result.output
        return tool_result
    except asyncio.CancelledError:
        # Propagate cooperative cancellation so outer layers can handle interrupts correctly.
        raise
    except Exception as e:
        return message.ToolResultMessage(
            call_id=tool_call.call_id,
            output_text=f"Tool {tool_call.tool_name} execution error: {e.__class__.__name__} {e}",
            status="error",
            tool_name=tool_call.tool_name,
        )


@dataclass
class ToolExecutionCallStarted:
    """Represents the start of a tool call execution."""

    tool_call: ToolCallRequest


@dataclass
class ToolExecutionResult:
    """Represents the completion of a tool call with its result."""

    tool_call: ToolCallRequest
    tool_result: message.ToolResultMessage
    # Whether this is the last ToolExecutionResult emitted in the current step.
    # Used by UI to decide whether to close the tree prefix.
    is_last_in_step: bool = False


@dataclass
class ToolExecutionTodoChange:
    """Represents a todo list change side effect emitted by a tool."""

    todos: list[TodoItem]


@dataclass
class ToolExecutionOutputDelta:
    """Represents incremental output emitted while a tool is still running."""

    tool_call: ToolCallRequest
    content: str


@dataclass
class ToolExecutionLongRunning:
    """Represents a tool call that has been running longer than the UI threshold."""

    tool_call: ToolCallRequest
    elapsed_seconds: float


ToolExecutorEvent = (
    ToolExecutionCallStarted
    | ToolExecutionResult
    | ToolExecutionTodoChange
    | ToolExecutionOutputDelta
    | ToolExecutionLongRunning
)


class ToolExecutor:
    """Execute and coordinate a batch of tool calls for a single step.

    The executor is responsible for:
    - Partitioning tool calls into sequential and concurrent tools
    - Running sequential tools one by one and concurrent tools in parallel
    - Emitting ToolCall/ToolResult events and tool side-effect events
    - Tracking unfinished calls so `on_interrupt()` can synthesize cancellation results
    """

    def __init__(
        self,
        *,
        context: ToolContext,
        registry: dict[str, type[ToolABC]],
        append_history: Callable[[Sequence[message.HistoryEvent]], None],
    ) -> None:
        self._context = context
        self._registry = registry
        self._append_history = append_history

        self._unfinished_calls: dict[str, ToolCallRequest] = {}
        self._call_event_emitted: set[str] = set()
        self._concurrent_tasks: set[asyncio.Task[None]] = set()
        self._sub_agent_session_ids: dict[str, str] = {}
        self._sub_agent_metadata_getters: dict[str, Callable[[], TaskMetadata | None]] = {}
        self._sub_agent_progress_getters: dict[str, Callable[[], str | None]] = {}

    async def run_tools(self, tool_calls: list[ToolCallRequest]) -> AsyncGenerator[ToolExecutorEvent]:
        """Run the given tool calls and yield execution events.

        Tool calls are partitioned into regular tools and sub-agent tools. Regular tools
        run sequentially, while sub-agent tools run concurrently. All results are
        appended to history via the injected `append_history` callback.
        """

        for tool_call in tool_calls:
            self._unfinished_calls[tool_call.call_id] = tool_call

        sequential_tool_calls, concurrent_tool_calls = self._partition_tool_calls(tool_calls)

        # Run sequential tools one by one.
        for idx, tool_call in enumerate(sequential_tool_calls):
            tool_call_event = self._build_tool_call_started(tool_call)
            self._call_event_emitted.add(tool_call.call_id)
            yield tool_call_event

            try:
                is_last_in_step = idx == len(sequential_tool_calls) - 1 and not concurrent_tool_calls
                async for exec_event in self._run_single_tool_call(tool_call):
                    if isinstance(exec_event, ToolExecutionResult):
                        exec_event.is_last_in_step = is_last_in_step
                    yield exec_event
            except asyncio.CancelledError:
                # Propagate cooperative cancellation so the agent task can be stopped.
                raise

        # Run concurrent tools (sub-agents, web tools) in parallel.
        if concurrent_tool_calls:
            event_queue: asyncio.Queue[ToolExecutorEvent | BaseException | None] = asyncio.Queue()
            execution_tasks: list[asyncio.Task[None]] = []
            for tool_call in concurrent_tool_calls:
                tool_call_event = self._build_tool_call_started(tool_call)
                self._call_event_emitted.add(tool_call.call_id)
                yield tool_call_event

                task = asyncio.create_task(self._forward_tool_call_events(tool_call, event_queue))
                self._register_concurrent_task(task)
                execution_tasks.append(task)

            completed_tasks = 0
            remaining_results = len(execution_tasks)
            try:
                while completed_tasks < len(execution_tasks):
                    # Do not swallow asyncio.CancelledError here. If the user interrupts
                    # the main agent, cancellation should still bubble up so the task can
                    # stop cleanly, matching the sequential path.
                    exec_event = await event_queue.get()
                    if exec_event is None:
                        completed_tasks += 1
                        continue
                    if isinstance(exec_event, BaseException):
                        raise exec_event
                    if isinstance(exec_event, ToolExecutionResult):
                        remaining_results -= 1
                        exec_event.is_last_in_step = remaining_results == 0
                    yield exec_event
            finally:
                for task in execution_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*execution_tasks, return_exceptions=True)

    def on_interrupt(self) -> Iterable[ToolExecutorEvent]:
        """Handle an interrupt by cancelling unfinished tool calls and synthesizing aborted results.

        - Cancels any running concurrent tool tasks so they stop emitting events.
        - For each unfinished tool call, yields a ToolExecutionCallStarted (if not
          already emitted for this step) followed by a ToolExecutionResult with
          error status and a standard cancellation output. The corresponding
          ToolResultMessage is appended to history via `append_history`.
        """

        events_to_yield: list[ToolExecutorEvent] = []

        # Cancel running concurrent tool tasks.
        for task in list(self._concurrent_tasks):
            if not task.done():
                task.cancel()
        self._concurrent_tasks.clear()

        if not self._unfinished_calls:
            return events_to_yield

        unfinished = list(self._unfinished_calls.items())
        for idx, (call_id, tool_call) in enumerate(unfinished):
            session_id = self._sub_agent_session_ids.get(call_id)
            # Get partial metadata from sub-agent if available
            metadata_getter = self._sub_agent_metadata_getters.get(call_id)
            task_metadata = metadata_getter() if metadata_getter is not None else None

            # Get partial progress (tool calls made) from sub-agent if available
            progress_getter = self._sub_agent_progress_getters.get(call_id)
            progress = progress_getter() if progress_getter is not None else None
            if progress:
                cancel_output = f"Overview of sub-agent transcript:\n{progress}\n\n{CANCEL_OUTPUT}"
            else:
                cancel_output = CANCEL_OUTPUT

            cancel_result = message.ToolResultMessage(
                call_id=tool_call.call_id,
                output_text=cancel_output,
                status="aborted",
                tool_name=tool_call.tool_name,
                ui_extra=SessionIdUIExtra(session_id=session_id) if session_id else None,
                task_metadata=task_metadata,
            )

            if call_id not in self._call_event_emitted:
                events_to_yield.append(ToolExecutionCallStarted(tool_call=tool_call))
                self._call_event_emitted.add(call_id)

            events_to_yield.append(
                ToolExecutionResult(
                    tool_call=tool_call,
                    tool_result=cancel_result,
                    is_last_in_step=idx == len(unfinished) - 1,
                )
            )

            self._append_history([cancel_result])
            self._unfinished_calls.pop(call_id, None)
            self._sub_agent_session_ids.pop(call_id, None)
            self._sub_agent_metadata_getters.pop(call_id, None)
            self._sub_agent_progress_getters.pop(call_id, None)

        return events_to_yield

    def _register_concurrent_task(self, task: asyncio.Task[None]) -> None:
        self._concurrent_tasks.add(task)

        def _cleanup(completed: asyncio.Task[None]) -> None:
            self._concurrent_tasks.discard(completed)

        task.add_done_callback(_cleanup)

    def _partition_tool_calls(
        self,
        tool_calls: list[ToolCallRequest],
    ) -> tuple[list[ToolCallRequest], list[ToolCallRequest]]:
        sequential_tool_calls: list[ToolCallRequest] = []
        concurrent_tool_calls: list[ToolCallRequest] = []
        for tool_call in tool_calls:
            tool_cls = self._registry.get(tool_call.tool_name)
            policy = (
                tool_cls.metadata().concurrency_policy if tool_cls is not None else ToolConcurrencyPolicy.SEQUENTIAL
            )
            if policy == ToolConcurrencyPolicy.CONCURRENT:
                concurrent_tool_calls.append(tool_call)
            else:
                sequential_tool_calls.append(tool_call)
        return sequential_tool_calls, concurrent_tool_calls

    def _build_tool_call_started(self, tool_call: ToolCallRequest) -> ToolExecutionCallStarted:
        return ToolExecutionCallStarted(tool_call=tool_call)

    async def _forward_tool_call_events(
        self,
        tool_call: ToolCallRequest,
        event_queue: asyncio.Queue[ToolExecutorEvent | BaseException | None],
    ) -> None:
        try:
            async for event in self._run_single_tool_call(tool_call):
                await event_queue.put(event)
        except BaseException as exc:
            await event_queue.put(exc)
            raise
        finally:
            await event_queue.put(None)

    async def _run_single_tool_call(self, tool_call: ToolCallRequest) -> AsyncGenerator[ToolExecutorEvent]:
        def _record_sub_agent_session_id(session_id: str) -> None:
            if tool_call.call_id not in self._sub_agent_session_ids:
                self._sub_agent_session_ids[tool_call.call_id] = session_id

        def _register_metadata_getter(getter: Callable[[], TaskMetadata | None]) -> None:
            self._sub_agent_metadata_getters[tool_call.call_id] = getter

        def _register_progress_getter(getter: Callable[[], str | None]) -> None:
            self._sub_agent_progress_getters[tool_call.call_id] = getter

        event_queue: asyncio.Queue[ToolExecutionOutputDelta | ToolExecutionLongRunning | None] = asyncio.Queue()

        async def _emit_tool_output_delta(content: str) -> None:
            if content:
                await event_queue.put(ToolExecutionOutputDelta(tool_call=tool_call, content=content))

        call_context = self._context.with_record_sub_agent_session_id(_record_sub_agent_session_id)
        call_context = call_context.with_register_sub_agent_metadata_getter(_register_metadata_getter)
        call_context = call_context.with_register_sub_agent_progress_getter(_register_progress_getter)
        call_context = call_context.with_emit_tool_output_delta(_emit_tool_output_delta)
        started_at = time.monotonic()
        tool_task = asyncio.create_task(run_tool(tool_call, self._registry, call_context))

        async def _emit_long_running_tool_event() -> None:
            await asyncio.sleep(LONG_RUNNING_TOOL_THRESHOLD_SECONDS)
            if not tool_task.done():
                await event_queue.put(
                    ToolExecutionLongRunning(
                        tool_call=tool_call,
                        elapsed_seconds=time.monotonic() - started_at,
                    )
                )

        async def _finish_event_queue(completed: asyncio.Task[message.ToolResultMessage]) -> None:
            try:
                await completed
            finally:
                await event_queue.put(None)

        long_running_task = asyncio.create_task(_emit_long_running_tool_event())
        queue_task = asyncio.create_task(_finish_event_queue(tool_task))
        try:
            while True:
                event = await event_queue.get()
                if event is None:
                    break
                yield event

            tool_result: message.ToolResultMessage = await tool_task
        finally:
            if not tool_task.done():
                tool_task.cancel()
            if not long_running_task.done():
                long_running_task.cancel()
            await asyncio.gather(queue_task, long_running_task, return_exceptions=True)

        self._append_history([tool_result])

        result_event = ToolExecutionResult(tool_call=tool_call, tool_result=tool_result)

        self._unfinished_calls.pop(tool_call.call_id, None)
        self._sub_agent_session_ids.pop(tool_call.call_id, None)
        self._sub_agent_metadata_getters.pop(tool_call.call_id, None)
        self._sub_agent_progress_getters.pop(tool_call.call_id, None)

        extra_events = self._build_tool_side_effect_events(tool_result)
        yield result_event
        for extra_event in extra_events:
            yield extra_event

    def _build_tool_side_effect_events(self, tool_result: message.ToolResultMessage) -> list[ToolExecutorEvent]:
        side_effects = tool_result.side_effects
        if not side_effects:
            return []

        side_effect_events: list[ToolExecutorEvent] = []

        for side_effect in side_effects:
            if side_effect == ToolSideEffect.TODO_CHANGE:
                todos: list[TodoItem] | None = None
                if isinstance(tool_result.ui_extra, TodoListUIExtra):
                    todos = tool_result.ui_extra.todo_list.todos
                if todos is not None:
                    side_effect_events.append(ToolExecutionTodoChange(todos=todos))

        return side_effect_events
