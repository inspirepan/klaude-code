import asyncio
from collections.abc import AsyncGenerator, Callable, Iterable, Sequence
from dataclasses import dataclass

from klaude_code import const
from klaude_code.core.tool.report_back_tool import ReportBackTool
from klaude_code.core.tool.tool_abc import ToolABC, ToolConcurrencyPolicy
from klaude_code.core.tool.truncation import truncate_tool_output
from klaude_code.protocol import model, tools


async def run_tool(tool_call: model.ToolCallItem, registry: dict[str, type[ToolABC]]) -> model.ToolResultItem:
    """Execute a tool call and return the result.

    Args:
        tool_call: The tool call to execute.
        registry: The tool registry mapping tool names to tool classes.

    Returns:
        The result of the tool execution.
    """
    # Special handling for report_back tool (not registered in global registry)
    if tool_call.name == tools.REPORT_BACK:
        tool_result = await ReportBackTool.call(tool_call.arguments)
        tool_result.call_id = tool_call.call_id
        tool_result.tool_name = tool_call.name
        return tool_result

    if tool_call.name not in registry:
        return model.ToolResultItem(
            call_id=tool_call.call_id,
            output=f"Tool {tool_call.name} not exists",
            status="error",
            tool_name=tool_call.name,
        )
    try:
        tool_result = await registry[tool_call.name].call(tool_call.arguments)
        tool_result.call_id = tool_call.call_id
        tool_result.tool_name = tool_call.name
        if tool_result.output:
            truncation_result = truncate_tool_output(tool_result.output, tool_call)
            tool_result.output = truncation_result.output
            if truncation_result.was_truncated and truncation_result.saved_file_path:
                tool_result.ui_extra = model.TruncationUIExtra(
                    saved_file_path=truncation_result.saved_file_path,
                    original_length=truncation_result.original_length,
                    truncated_length=truncation_result.truncated_length,
                )
        return tool_result
    except asyncio.CancelledError:
        # Propagate cooperative cancellation so outer layers can handle interrupts correctly.
        raise
    except Exception as e:
        return model.ToolResultItem(
            call_id=tool_call.call_id,
            output=f"Tool {tool_call.name} execution error: {e.__class__.__name__} {e}",
            status="error",
            tool_name=tool_call.name,
        )


@dataclass
class ToolExecutionCallStarted:
    """Represents the start of a tool call execution."""

    tool_call: model.ToolCallItem


@dataclass
class ToolExecutionResult:
    """Represents the completion of a tool call with its result."""

    tool_call: model.ToolCallItem
    tool_result: model.ToolResultItem


@dataclass
class ToolExecutionTodoChange:
    """Represents a todo list change side effect emitted by a tool."""

    todos: list[model.TodoItem]


ToolExecutorEvent = ToolExecutionCallStarted | ToolExecutionResult | ToolExecutionTodoChange


class ToolExecutor:
    """Execute and coordinate a batch of tool calls for a single turn.

    The executor is responsible for:
    - Partitioning tool calls into sequential and concurrent tools
    - Running sequential tools one by one and concurrent tools in parallel
    - Emitting ToolCall/ToolResult events and tool side-effect events
    - Tracking unfinished calls so `cancel()` can synthesize cancellation results
    """

    def __init__(
        self,
        *,
        registry: dict[str, type[ToolABC]],
        append_history: Callable[[Sequence[model.ConversationItem]], None],
    ) -> None:
        self._registry = registry
        self._append_history = append_history

        self._unfinished_calls: dict[str, model.ToolCallItem] = {}
        self._call_event_emitted: set[str] = set()
        self._concurrent_tasks: set[asyncio.Task[list[ToolExecutorEvent]]] = set()

    async def run_tools(self, tool_calls: list[model.ToolCallItem]) -> AsyncGenerator[ToolExecutorEvent]:
        """Run the given tool calls and yield execution events.

        Tool calls are partitioned into regular tools and sub-agent tools. Regular tools
        run sequentially, while sub-agent tools run concurrently. All results are
        appended to history via the injected `append_history` callback.
        """

        for tool_call in tool_calls:
            self._unfinished_calls[tool_call.call_id] = tool_call

        sequential_tool_calls, concurrent_tool_calls = self._partition_tool_calls(tool_calls)

        # Run sequential tools one by one.
        for tool_call in sequential_tool_calls:
            tool_call_event = self._build_tool_call_started(tool_call)
            self._call_event_emitted.add(tool_call.call_id)
            yield tool_call_event

            try:
                result_events = await self._run_single_tool_call(tool_call)
            except asyncio.CancelledError:
                # Propagate cooperative cancellation so the agent task can be stopped.
                raise

            for exec_event in result_events:
                yield exec_event

        # Run concurrent tools (sub-agents, web tools) in parallel.
        if concurrent_tool_calls:
            execution_tasks: list[asyncio.Task[list[ToolExecutorEvent]]] = []
            for tool_call in concurrent_tool_calls:
                tool_call_event = self._build_tool_call_started(tool_call)
                self._call_event_emitted.add(tool_call.call_id)
                yield tool_call_event

                task = asyncio.create_task(self._run_single_tool_call(tool_call))
                self._register_concurrent_task(task)
                execution_tasks.append(task)

            for task in asyncio.as_completed(execution_tasks):
                # Do not swallow asyncio.CancelledError here:
                # - If the user interrupts the main agent, the executor cancels the
                #   outer agent task, which should propagate cancellation up through
                #   tool execution so the task can terminate and emit TaskFinishEvent.
                # - Sub-agent tool tasks cancelled via ToolExecutor.cancel() are
                #   handled by synthesizing ToolExecutionResult events; any
                #   CancelledError raised here should still bubble up so the
                #   calling agent can stop cleanly, matching pre-refactor behavior.
                result_events = await task

                for exec_event in result_events:
                    yield exec_event

    def cancel(self) -> Iterable[ToolExecutorEvent]:
        """Cancel unfinished tool calls and synthesize error results.

        - Cancels any running concurrent tool tasks so they stop emitting events.
        - For each unfinished tool call, yields a ToolExecutionCallStarted (if not
          already emitted for this turn) followed by a ToolExecutionResult with
          error status and a standard cancellation output. The corresponding
          ToolResultItem is appended to history via `append_history`.
        """

        events_to_yield: list[ToolExecutorEvent] = []

        # Cancel running concurrent tool tasks.
        for task in list(self._concurrent_tasks):
            if not task.done():
                task.cancel()
        self._concurrent_tasks.clear()

        if not self._unfinished_calls:
            return events_to_yield

        for call_id, tool_call in list(self._unfinished_calls.items()):
            cancel_result = model.ToolResultItem(
                call_id=tool_call.call_id,
                output=const.CANCEL_OUTPUT,
                status="error",
                tool_name=tool_call.name,
                ui_extra=None,
            )

            if call_id not in self._call_event_emitted:
                events_to_yield.append(ToolExecutionCallStarted(tool_call=tool_call))
                self._call_event_emitted.add(call_id)

            events_to_yield.append(ToolExecutionResult(tool_call=tool_call, tool_result=cancel_result))

            self._append_history([cancel_result])
            self._unfinished_calls.pop(call_id, None)

        return events_to_yield

    def _register_concurrent_task(self, task: asyncio.Task[list[ToolExecutorEvent]]) -> None:
        self._concurrent_tasks.add(task)

        def _cleanup(completed: asyncio.Task[list[ToolExecutorEvent]]) -> None:
            self._concurrent_tasks.discard(completed)

        task.add_done_callback(_cleanup)

    def _partition_tool_calls(
        self,
        tool_calls: list[model.ToolCallItem],
    ) -> tuple[list[model.ToolCallItem], list[model.ToolCallItem]]:
        sequential_tool_calls: list[model.ToolCallItem] = []
        concurrent_tool_calls: list[model.ToolCallItem] = []
        for tool_call in tool_calls:
            tool_cls = self._registry.get(tool_call.name)
            policy = (
                tool_cls.metadata().concurrency_policy if tool_cls is not None else ToolConcurrencyPolicy.SEQUENTIAL
            )
            if policy == ToolConcurrencyPolicy.CONCURRENT:
                concurrent_tool_calls.append(tool_call)
            else:
                sequential_tool_calls.append(tool_call)
        return sequential_tool_calls, concurrent_tool_calls

    def _build_tool_call_started(self, tool_call: model.ToolCallItem) -> ToolExecutionCallStarted:
        return ToolExecutionCallStarted(tool_call=tool_call)

    async def _run_single_tool_call(self, tool_call: model.ToolCallItem) -> list[ToolExecutorEvent]:
        tool_result: model.ToolResultItem = await run_tool(tool_call, self._registry)

        self._append_history([tool_result])

        result_event = ToolExecutionResult(tool_call=tool_call, tool_result=tool_result)

        self._unfinished_calls.pop(tool_call.call_id, None)

        extra_events = self._build_tool_side_effect_events(tool_result)
        return [result_event, *extra_events]

    def _build_tool_side_effect_events(self, tool_result: model.ToolResultItem) -> list[ToolExecutorEvent]:
        side_effects = tool_result.side_effects
        if not side_effects:
            return []

        side_effect_events: list[ToolExecutorEvent] = []

        for side_effect in side_effects:
            if side_effect == model.ToolSideEffect.TODO_CHANGE:
                todos: list[model.TodoItem] | None = None
                if isinstance(tool_result.ui_extra, model.TodoListUIExtra):
                    todos = tool_result.ui_extra.todo_list.todos
                if todos is not None:
                    side_effect_events.append(ToolExecutionTodoChange(todos=todos))

        return side_effect_events
