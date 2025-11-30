from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Callable, MutableMapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from klaude_code import const
from klaude_code.core.reminders import Reminder
from klaude_code.core.tool import TodoContext, ToolABC
from klaude_code.core.turn import TurnError, TurnExecutionContext, TurnExecutor
from klaude_code.protocol import events, model
from klaude_code.trace import DebugType, log_debug

if TYPE_CHECKING:
    from klaude_code.core.agent import AgentProfile


class MetadataAccumulator:
    """Accumulates response metadata across multiple turns.

    Tracks usage statistics including tokens, latency, and throughput,
    merging them into a single aggregated result.
    """

    def __init__(self, model_name: str) -> None:
        self._accumulated = model.ResponseMetadataItem(model_name=model_name)
        self._throughput_weighted_sum: float = 0.0
        self._throughput_tracked_tokens: int = 0

    def add(self, turn_metadata: model.ResponseMetadataItem) -> None:
        """Merge a turn's metadata into the accumulated state."""
        accumulated = self._accumulated
        usage = turn_metadata.usage

        if usage is not None:
            if accumulated.usage is None:
                accumulated.usage = model.Usage()
            acc_usage = accumulated.usage
            acc_usage.input_tokens += usage.input_tokens
            acc_usage.cached_tokens += usage.cached_tokens
            acc_usage.reasoning_tokens += usage.reasoning_tokens
            acc_usage.output_tokens += usage.output_tokens
            acc_usage.total_tokens += usage.total_tokens

            if usage.context_usage_percent is not None:
                acc_usage.context_usage_percent = usage.context_usage_percent

            if usage.first_token_latency_ms is not None:
                if acc_usage.first_token_latency_ms is None:
                    acc_usage.first_token_latency_ms = usage.first_token_latency_ms
                else:
                    acc_usage.first_token_latency_ms = min(
                        acc_usage.first_token_latency_ms,
                        usage.first_token_latency_ms,
                    )

            if usage.throughput_tps is not None:
                current_output = usage.output_tokens
                if current_output > 0:
                    self._throughput_weighted_sum += usage.throughput_tps * current_output
                    self._throughput_tracked_tokens += current_output

            # Accumulate costs
            if usage.input_cost is not None:
                acc_usage.input_cost = (acc_usage.input_cost or 0.0) + usage.input_cost
            if usage.output_cost is not None:
                acc_usage.output_cost = (acc_usage.output_cost or 0.0) + usage.output_cost
            if usage.cache_read_cost is not None:
                acc_usage.cache_read_cost = (acc_usage.cache_read_cost or 0.0) + usage.cache_read_cost
            if usage.total_cost is not None:
                acc_usage.total_cost = (acc_usage.total_cost or 0.0) + usage.total_cost

        if turn_metadata.provider is not None:
            accumulated.provider = turn_metadata.provider
        if turn_metadata.model_name:
            accumulated.model_name = turn_metadata.model_name
        if turn_metadata.response_id:
            accumulated.response_id = turn_metadata.response_id
        if turn_metadata.status is not None:
            accumulated.status = turn_metadata.status
        if turn_metadata.error_reason is not None:
            accumulated.error_reason = turn_metadata.error_reason

    def finalize(self, task_duration_s: float) -> model.ResponseMetadataItem:
        """Return the final accumulated metadata with computed throughput and duration."""
        accumulated = self._accumulated
        if accumulated.usage is not None:
            if self._throughput_tracked_tokens > 0:
                accumulated.usage.throughput_tps = self._throughput_weighted_sum / self._throughput_tracked_tokens
            else:
                accumulated.usage.throughput_tps = None

        accumulated.task_duration_s = task_duration_s
        return accumulated


@dataclass
class TaskExecutionContext:
    """Execution context required to run a task."""

    session_id: str
    profile: AgentProfile
    get_conversation_history: Callable[[], list[model.ConversationItem]]
    append_history: Callable[[Sequence[model.ConversationItem]], None]
    tool_registry: dict[str, type[ToolABC]]
    file_tracker: MutableMapping[str, float]
    todo_context: TodoContext
    # For reminder processing - needs access to session
    process_reminder: Callable[[Reminder], AsyncGenerator[events.DeveloperMessageEvent, None]]
    sub_agent_state: model.SubAgentState | None


class TaskExecutor:
    """Executes a complete task (multiple turns until no more tool calls).

    Manages task-level state like metadata accumulation and retry logic.
    """

    def __init__(self, context: TaskExecutionContext) -> None:
        self._context = context
        self._current_turn: TurnExecutor | None = None
        self._started_at: float = 0.0

    @property
    def current_turn(self) -> TurnExecutor | None:
        return self._current_turn

    def cancel(self) -> list[events.Event]:
        """Cancel the current turn and return any resulting events."""
        ui_events: list[events.Event] = []
        if self._current_turn is not None:
            ui_events.extend(self._current_turn.cancel())
            self._current_turn = None
        return ui_events

    async def run(self, user_input: model.UserInputPayload) -> AsyncGenerator[events.Event, None]:
        """Execute the task, yielding events as they occur."""
        ctx = self._context
        self._started_at = time.perf_counter()

        yield events.TaskStartEvent(
            session_id=ctx.session_id,
            sub_agent_state=ctx.sub_agent_state,
        )

        ctx.append_history([model.UserMessageItem(content=user_input.text, images=user_input.images)])

        profile = ctx.profile
        metadata_accumulator = MetadataAccumulator(model_name=profile.llm_client.model_name)
        last_assistant_message: events.AssistantMessageEvent | None = None

        while True:
            # Process reminders at the start of each turn
            for reminder in profile.reminders:
                async for event in ctx.process_reminder(reminder):
                    yield event

            turn_context = TurnExecutionContext(
                session_id=ctx.session_id,
                get_conversation_history=ctx.get_conversation_history,
                append_history=ctx.append_history,
                llm_client=profile.llm_client,
                system_prompt=profile.system_prompt,
                tools=profile.tools,
                tool_registry=ctx.tool_registry,
                file_tracker=ctx.file_tracker,
                todo_context=ctx.todo_context,
            )

            turn: TurnExecutor | None = None
            turn_succeeded = False
            last_error_message: str | None = None

            for attempt in range(const.MAX_FAILED_TURN_RETRIES + 1):
                turn = TurnExecutor(turn_context)
                self._current_turn = turn

                try:
                    async for turn_event in turn.run():
                        match turn_event:
                            case events.AssistantMessageEvent() as am:
                                if am.content.strip() != "":
                                    last_assistant_message = am
                                yield am
                            case events.ResponseMetadataEvent() as e:
                                metadata_accumulator.add(e.metadata)
                            case _:
                                yield turn_event

                    turn_succeeded = True
                    break
                except TurnError as e:
                    last_error_message = str(e)
                    if attempt < const.MAX_FAILED_TURN_RETRIES:
                        delay = _retry_delay_seconds(attempt + 1)
                        error_msg = f"Retrying {attempt + 1}/{const.MAX_FAILED_TURN_RETRIES} in {delay:.1f}s"
                        if last_error_message:
                            error_msg = f"{error_msg} - {last_error_message}"
                        yield events.ErrorEvent(error_message=error_msg, can_retry=True)
                        await asyncio.sleep(delay)
                finally:
                    self._current_turn = None

            if not turn_succeeded:
                log_debug(
                    "Maximum consecutive failed turns reached, aborting task",
                    style="red",
                    debug_type=DebugType.EXECUTION,
                )
                final_error = f"Turn failed after {const.MAX_FAILED_TURN_RETRIES} retries."
                if last_error_message:
                    final_error = f"{last_error_message}\n{final_error}"
                yield events.ErrorEvent(error_message=final_error, can_retry=False)
                return

            if turn is None or not turn.has_tool_call:
                break

        # Finalize metadata
        task_duration_s = time.perf_counter() - self._started_at
        accumulated = metadata_accumulator.finalize(task_duration_s)

        yield events.ResponseMetadataEvent(metadata=accumulated, session_id=ctx.session_id)
        ctx.append_history([accumulated])
        yield events.TaskFinishEvent(
            session_id=ctx.session_id,
            task_result=last_assistant_message.content if last_assistant_message else "",
        )


def _retry_delay_seconds(attempt: int) -> float:
    """Compute exponential backoff delay for the given attempt count."""
    capped_attempt = max(1, attempt)
    delay = const.INITIAL_RETRY_DELAY_S * (2 ** (capped_attempt - 1))
    return min(delay, const.MAX_RETRY_DELAY_S)
