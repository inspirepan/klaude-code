from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Callable, Sequence
from dataclasses import dataclass

from klaude_code.const import INITIAL_RETRY_DELAY_S, MAX_FAILED_TURN_RETRIES, MAX_RETRY_DELAY_S
from klaude_code.core.agent_profile import AgentProfile, Reminder
from klaude_code.core.compaction import (
    CompactionReason,
    is_context_overflow,
    run_compaction,
    should_compact_threshold,
)
from klaude_code.core.tool import FileTracker, TodoContext, ToolABC
from klaude_code.core.tool.context import RunSubtask
from klaude_code.core.turn import TurnError, TurnExecutionContext, TurnExecutor
from klaude_code.llm import LLMClientABC
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, message, model
from klaude_code.session.session import Session


class MetadataAccumulator:
    """Accumulates response metadata across multiple turns.

    Tracks usage statistics including tokens, latency, and throughput,
    merging them into a single aggregated result.
    """

    def __init__(self, model_name: str) -> None:
        self._main_agent = model.TaskMetadata(model_name=model_name)  # Main agent metadata
        self._sub_agent_metadata: list[model.TaskMetadata] = []
        self._throughput_weighted_sum: float = 0.0
        self._throughput_tracked_tokens: int = 0
        self._first_token_latency_sum: float = 0.0
        self._first_token_latency_count: int = 0
        self._turn_count: int = 0

    def add(self, turn_usage: model.Usage) -> None:
        """Merge a turn's usage into the accumulated state."""
        self._turn_count += 1
        usage = turn_usage

        if self._main_agent.usage is None:
            self._main_agent.usage = model.Usage()
        acc_usage = self._main_agent.usage

        model.TaskMetadata.merge_usage(acc_usage, usage)
        acc_usage.currency = usage.currency

        if usage.context_size is not None:
            acc_usage.context_size = usage.context_size
        if usage.context_limit is not None:
            acc_usage.context_limit = usage.context_limit

        if usage.first_token_latency_ms is not None:
            self._first_token_latency_sum += usage.first_token_latency_ms
            self._first_token_latency_count += 1

        if usage.throughput_tps is not None:
            current_output = usage.output_tokens
            if current_output > 0:
                self._throughput_weighted_sum += usage.throughput_tps * current_output
                self._throughput_tracked_tokens += current_output

        if usage.provider is not None:
            self._main_agent.provider = usage.provider
        if usage.model_name:
            self._main_agent.model_name = usage.model_name

    def add_sub_agent_metadata(self, sub_agent_metadata: model.TaskMetadata) -> None:
        """Add sub-agent task metadata to the accumulated state."""
        self._sub_agent_metadata.append(sub_agent_metadata)

    def get_partial(self, task_duration_s: float) -> model.TaskMetadata | None:
        """Return a snapshot of main agent metadata without modifying accumulator state.

        Returns None if no usage data has been accumulated yet.
        """
        if self._main_agent.usage is None:
            return None

        # Create a copy to avoid modifying the original
        usage_copy = self._main_agent.usage.model_copy(deep=True)

        if self._throughput_tracked_tokens > 0:
            usage_copy.throughput_tps = self._throughput_weighted_sum / self._throughput_tracked_tokens
        else:
            usage_copy.throughput_tps = None

        if self._first_token_latency_count > 0:
            usage_copy.first_token_latency_ms = self._first_token_latency_sum / self._first_token_latency_count
        else:
            usage_copy.first_token_latency_ms = None

        return model.TaskMetadata(
            model_name=self._main_agent.model_name,
            provider=self._main_agent.provider,
            usage=usage_copy,
            task_duration_s=task_duration_s,
            turn_count=self._turn_count,
        )

    def get_partial_item(self, task_duration_s: float) -> model.TaskMetadataItem | None:
        """Return a snapshot of full metadata (main + sub-agents) without modifying state.

        Returns None if no usage data has been accumulated yet.
        """
        main_agent = self.get_partial(task_duration_s)
        if main_agent is None:
            return None

        return model.TaskMetadataItem(
            main_agent=main_agent,
            sub_agent_task_metadata=list(self._sub_agent_metadata),
        )

    def finalize(self, task_duration_s: float) -> model.TaskMetadataItem:
        """Return the final accumulated metadata with computed throughput and duration."""
        if self._main_agent.usage is not None:
            if self._throughput_tracked_tokens > 0:
                self._main_agent.usage.throughput_tps = self._throughput_weighted_sum / self._throughput_tracked_tokens
            else:
                self._main_agent.usage.throughput_tps = None

            if self._first_token_latency_count > 0:
                self._main_agent.usage.first_token_latency_ms = (
                    self._first_token_latency_sum / self._first_token_latency_count
                )
            else:
                self._main_agent.usage.first_token_latency_ms = None

        self._main_agent.task_duration_s = task_duration_s
        self._main_agent.turn_count = self._turn_count
        return model.TaskMetadataItem(main_agent=self._main_agent, sub_agent_task_metadata=self._sub_agent_metadata)


@dataclass
class SessionContext:
    """Shared session-level context for task and turn execution.

    Contains common fields that both TaskExecutionContext and TurnExecutionContext need.
    """

    session_id: str
    get_conversation_history: Callable[[], list[message.HistoryEvent]]
    append_history: Callable[[Sequence[message.HistoryEvent]], None]
    file_tracker: FileTracker
    todo_context: TodoContext
    run_subtask: RunSubtask | None


@dataclass
class TaskExecutionContext:
    """Execution context required to run a task."""

    session: Session
    session_ctx: SessionContext
    profile: AgentProfile
    tool_registry: dict[str, type[ToolABC]]
    # For reminder processing - needs access to session
    process_reminder: Callable[[Reminder], AsyncGenerator[events.DeveloperMessageEvent]]
    sub_agent_state: model.SubAgentState | None
    # LLM client for compaction (uses main if not set)
    compact_llm_client: LLMClientABC | None = None


class TaskExecutor:
    """Executes a complete task (multiple turns until no more tool calls).

    Manages task-level state like metadata accumulation and retry logic.
    """

    def __init__(self, context: TaskExecutionContext) -> None:
        self._context = context
        self._current_turn: TurnExecutor | None = None
        self._started_at: float = 0.0
        self._metadata_accumulator: MetadataAccumulator | None = None

    def get_partial_metadata(self) -> model.TaskMetadata | None:
        """Get the currently accumulated metadata without finalizing.

        Returns partial metadata that can be used if the task is interrupted.
        """
        if self._metadata_accumulator is None or self._started_at <= 0:
            return None
        task_duration_s = time.perf_counter() - self._started_at
        return self._metadata_accumulator.get_partial(task_duration_s)

    def cancel(self) -> list[events.Event]:
        """Cancel the current turn and return any resulting events including metadata."""
        ui_events: list[events.Event] = []
        if self._current_turn is not None:
            for evt in self._current_turn.cancel():
                # Collect sub-agent task metadata from cancelled tool results
                if (
                    isinstance(evt, events.ToolResultEvent)
                    and evt.task_metadata is not None
                    and self._metadata_accumulator is not None
                ):
                    self._metadata_accumulator.add_sub_agent_metadata(evt.task_metadata)
                ui_events.append(evt)
            self._current_turn = None

        # Emit partial metadata on cancellation
        if self._metadata_accumulator is not None and self._started_at > 0:
            task_duration_s = time.perf_counter() - self._started_at
            accumulated = self._metadata_accumulator.get_partial_item(task_duration_s)
            if accumulated is not None:
                session_id = self._context.session_ctx.session_id
                ui_events.append(events.TaskMetadataEvent(metadata=accumulated, session_id=session_id))
                self._context.session_ctx.append_history([accumulated])

        return ui_events

    async def run(self, user_input: message.UserInputPayload) -> AsyncGenerator[events.Event]:
        """Execute the task, yielding events as they occur."""
        ctx = self._context
        session_ctx = ctx.session_ctx
        self._started_at = time.perf_counter()

        yield events.TaskStartEvent(
            session_id=session_ctx.session_id,
            sub_agent_state=ctx.sub_agent_state,
            model_id=ctx.profile.llm_client.get_llm_config().model_id,
        )
        del user_input  # Persisted by the operation handler before launching the task.

        profile = ctx.profile
        self._metadata_accumulator = MetadataAccumulator(model_name=profile.llm_client.model_name)
        metadata_accumulator = self._metadata_accumulator

        while True:
            # Process reminders at the start of each turn
            for reminder in profile.reminders:
                async for event in ctx.process_reminder(reminder):
                    yield event

            # Threshold-based compaction before starting a new turn.
            # This matters for multi-turn tool loops where no new user input occurs.
            if ctx.sub_agent_state is None and should_compact_threshold(
                session=ctx.session,
                config=None,
                llm_config=profile.llm_client.get_llm_config(),
            ):
                log_debug("[Compact] start", debug_type=DebugType.RESPONSE)
                yield events.CompactionStartEvent(
                    session_id=session_ctx.session_id,
                    reason=CompactionReason.THRESHOLD.value,
                )
                try:
                    compact_client = ctx.compact_llm_client or profile.llm_client
                    result = await run_compaction(
                        session=ctx.session,
                        reason=CompactionReason.THRESHOLD,
                        focus=None,
                        llm_client=compact_client,
                        llm_config=compact_client.get_llm_config(),
                    )
                    log_debug("[Compact] result", str(result.to_entry()), debug_type=DebugType.RESPONSE)

                    session_ctx.append_history([result.to_entry()])
                    yield events.CompactionEndEvent(
                        session_id=session_ctx.session_id,
                        reason=CompactionReason.THRESHOLD.value,
                        aborted=False,
                        will_retry=False,
                        tokens_before=result.tokens_before,
                        kept_from_index=result.first_kept_index,
                        summary=result.summary,
                        kept_items_brief=result.kept_items_brief,
                    )
                except asyncio.CancelledError:
                    yield events.CompactionEndEvent(
                        session_id=session_ctx.session_id,
                        reason=CompactionReason.THRESHOLD.value,
                        aborted=True,
                        will_retry=False,
                    )
                    raise
                except Exception as e:
                    import traceback

                    # For threshold compaction, failure should not take down the task.
                    log_debug(
                        "[Compact] error",
                        str(e.__class__.__name__),
                        str(e),
                        traceback.format_exc(),
                        debug_type=DebugType.RESPONSE,
                    )
                    yield events.CompactionEndEvent(
                        session_id=session_ctx.session_id,
                        reason=CompactionReason.THRESHOLD.value,
                        aborted=True,
                        will_retry=False,
                    )

            turn_context = TurnExecutionContext(
                session_ctx=session_ctx,
                llm_client=profile.llm_client,
                system_prompt=profile.system_prompt,
                tools=profile.tools,
                tool_registry=ctx.tool_registry,
                sub_agent_state=ctx.sub_agent_state,
            )

            turn: TurnExecutor | None = None
            turn_succeeded = False
            last_error_message: str | None = None

            for attempt in range(MAX_FAILED_TURN_RETRIES + 1):
                turn = TurnExecutor(turn_context)
                self._current_turn = turn

                try:
                    async for e in turn.run():
                        match e:
                            case events.ResponseCompleteEvent() as am:
                                yield am
                            case events.UsageEvent() as e:
                                metadata_accumulator.add(e.usage)
                                yield e
                            case events.ToolResultEvent() as e:
                                # Collect sub-agent task metadata from tool results
                                if e.task_metadata is not None:
                                    metadata_accumulator.add_sub_agent_metadata(e.task_metadata)
                                yield e
                            case _:
                                yield e

                    turn_succeeded = True
                    break
                except TurnError as e:
                    last_error_message = str(e)
                    if is_context_overflow(last_error_message):
                        yield events.CompactionStartEvent(
                            session_id=session_ctx.session_id,
                            reason=CompactionReason.OVERFLOW.value,
                        )
                        try:
                            log_debug("[Compact:Overflow] start", debug_type=DebugType.RESPONSE)
                            compact_client = ctx.compact_llm_client or profile.llm_client
                            result = await run_compaction(
                                session=ctx.session,
                                reason=CompactionReason.OVERFLOW,
                                focus=None,
                                llm_client=compact_client,
                                llm_config=compact_client.get_llm_config(),
                            )
                            log_debug(
                                "[Compact:Overflow] result", str(result.to_entry()), debug_type=DebugType.RESPONSE
                            )
                            session_ctx.append_history([result.to_entry()])
                            yield events.CompactionEndEvent(
                                session_id=session_ctx.session_id,
                                reason=CompactionReason.OVERFLOW.value,
                                aborted=False,
                                will_retry=True,
                                tokens_before=result.tokens_before,
                                kept_from_index=result.first_kept_index,
                                summary=result.summary,
                                kept_items_brief=result.kept_items_brief,
                            )
                            continue
                        except asyncio.CancelledError:
                            yield events.CompactionEndEvent(
                                session_id=session_ctx.session_id,
                                reason=CompactionReason.OVERFLOW.value,
                                aborted=True,
                                will_retry=True,
                            )
                            raise
                        except Exception as exc:
                            import traceback

                            log_debug(
                                "[Compact:Overflow] error",
                                str(exc.__class__.__name__),
                                str(exc),
                                traceback.format_exc(),
                                debug_type=DebugType.RESPONSE,
                            )
                            last_error_message = f"{last_error_message} (compaction failed: {exc})"
                            yield events.CompactionEndEvent(
                                session_id=session_ctx.session_id,
                                reason=CompactionReason.OVERFLOW.value,
                                aborted=True,
                                will_retry=False,
                            )
                    if attempt < MAX_FAILED_TURN_RETRIES:
                        delay = _retry_delay_seconds(attempt + 1)
                        error_msg = f"Retrying {attempt + 1}/{MAX_FAILED_TURN_RETRIES} in {delay:.1f}s"
                        if last_error_message:
                            error_msg = f"{error_msg} - {last_error_message}"
                        yield events.ErrorEvent(
                            error_message=error_msg, can_retry=True, session_id=session_ctx.session_id
                        )
                        await asyncio.sleep(delay)
                finally:
                    self._current_turn = None

            if not turn_succeeded:
                log_debug(
                    "Maximum consecutive failed turns reached, aborting task",
                    style="red",
                    debug_type=DebugType.EXECUTION,
                )
                final_error = f"Turn failed after {MAX_FAILED_TURN_RETRIES} retries."
                if last_error_message:
                    final_error = f"{last_error_message}\n{final_error}"
                yield events.ErrorEvent(error_message=final_error, can_retry=False, session_id=session_ctx.session_id)
                return

            if turn is None or turn.task_finished:
                # Empty result should retry instead of finishing
                if turn is not None and not turn.task_result.strip():
                    if ctx.sub_agent_state is not None:
                        error_msg = "Sub-agent returned empty result, retrying…"
                    else:
                        error_msg = "Agent returned empty result, retrying…"
                    yield events.ErrorEvent(error_message=error_msg, can_retry=True, session_id=session_ctx.session_id)
                    continue
                break

        # Finalize metadata
        task_duration_s = time.perf_counter() - self._started_at
        accumulated = metadata_accumulator.finalize(task_duration_s)

        yield events.TaskMetadataEvent(metadata=accumulated, session_id=session_ctx.session_id)
        session_ctx.append_history([accumulated])

        # Get task result from turn
        task_result = turn.task_result if turn is not None else ""
        has_structured_output = turn.has_structured_output if turn is not None else False

        yield events.TaskFinishEvent(
            session_id=session_ctx.session_id,
            task_result=task_result,
            has_structured_output=has_structured_output,
        )


def _retry_delay_seconds(attempt: int) -> float:
    """Compute exponential backoff delay for the given attempt count."""
    capped_attempt = max(1, attempt)
    delay = INITIAL_RETRY_DELAY_S * (2 ** (capped_attempt - 1))
    return min(delay, MAX_RETRY_DELAY_S)
