from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.attachments.collection import collect_attachments
from klaude_code.agent.attachments.state import reset_attachment_loaded_flags
from klaude_code.agent.cache_break_detection import CacheBreakReport, CacheTracker
from klaude_code.agent.compaction import (
    CompactionReason,
    is_context_overflow,
    run_compaction,
    should_compact_threshold,
)
from klaude_code.agent.handoff import HandoffManager, run_handoff
from klaude_code.agent.rewind import RewindManager
from klaude_code.agent.runtime.llm import FallbackLLMClient
from klaude_code.agent.turn import TurnError, TurnExecutionContext, TurnExecutor
from klaude_code.const import (
    INITIAL_RETRY_DELAY_S,
    MAX_EMPTY_RESPONSE_RETRIES,
    MAX_FAILED_TURN_RETRIES,
    MAX_RETRY_DELAY_S,
)
from klaude_code.llm import LLMClientABC
from klaude_code.log import DebugType, log_debug
from klaude_code.prompts.messages import EMPTY_RESPONSE_CONTINUATION_PROMPT
from klaude_code.protocol import events, llm_param, message, tools, user_interaction
from klaude_code.protocol.models import (
    FileChangeSummary,
    FileStatus,
    SubAgentState,
    TaskMetadata,
    TaskMetadataItem,
    Usage,
)
from klaude_code.session.session import Session
from klaude_code.tool import FileTracker, TodoContext, ToolABC, get_registry
from klaude_code.tool.core.context import RunSubtask

type RequestUserInteraction = Callable[
    [
        str,
        user_interaction.UserInteractionSource,
        user_interaction.UserInteractionRequestPayload,
        str | None,
    ],
    Awaitable[user_interaction.UserInteractionResponse],
]


class MetadataAccumulator:
    """Accumulates response metadata across multiple turns.

    Tracks usage statistics including tokens, latency, and throughput,
    merging them into a single aggregated result.
    """

    def __init__(self, model_name: str) -> None:
        self._main_agent = TaskMetadata(model_name=model_name)
        self._sub_agent_metadata: list[TaskMetadata] = []
        self._throughput_weighted_sum: float = 0.0
        self._throughput_tracked_tokens: int = 0
        self._first_token_latency_sum: float = 0.0
        self._first_token_latency_count: int = 0
        self._turn_count: int = 0
        self.cache = CacheTracker()

    @property
    def prev_turn_input_tokens(self) -> int:
        """Input token count from the most recent successful turn."""
        return self.cache.prev_turn_input_tokens

    # Convenience aliases so callers read through the same path.
    @property
    def last_turn_cache_hit_rate(self) -> float | None:
        return self.cache.last_hit_rate

    @property
    def last_turn_cached_tokens(self) -> int:
        return self.cache.last_cached_tokens

    @property
    def last_turn_prev_input_tokens(self) -> int:
        return self.cache.last_prev_input_tokens

    def add(self, turn_usage: Usage) -> CacheBreakReport | None:
        """Merge a turn's usage into the accumulated state.

        Returns a ``CacheBreakReport`` when a prompt-prefix cache break is
        detected, ``None`` otherwise.
        """
        self._turn_count += 1
        usage = turn_usage

        if self._main_agent.usage is None:
            self._main_agent.usage = Usage()
        acc_usage = self._main_agent.usage

        TaskMetadata.merge_usage(acc_usage, usage)
        acc_usage.currency = usage.currency

        if usage.context_size is not None:
            acc_usage.context_size = usage.context_size
        if usage.context_limit is not None:
            acc_usage.context_limit = usage.context_limit
        if usage.max_tokens is not None:
            acc_usage.max_tokens = usage.max_tokens

        if usage.first_token_latency_ms is not None:
            self._first_token_latency_sum += usage.first_token_latency_ms
            self._first_token_latency_count += 1

        if usage.throughput_tps is not None:
            current_output = usage.output_tokens
            if current_output > 0:
                self._throughput_weighted_sum += usage.throughput_tps * current_output
                self._throughput_tracked_tokens += current_output

        cache_break = self.cache.update(usage)

        if usage.provider is not None:
            self._main_agent.provider = usage.provider
        if usage.model_name:
            self._main_agent.model_name = usage.model_name

        return cache_break

    def add_sub_agent_metadata(self, sub_agent_metadata: TaskMetadata) -> None:
        """Add sub-agent task metadata to the accumulated state."""
        self._sub_agent_metadata.append(sub_agent_metadata)

    def get_partial(self, task_duration_s: float) -> TaskMetadata | None:
        """Return a snapshot of main agent metadata without modifying accumulator state.

        Returns None if no usage data has been accumulated yet.
        """
        if self._main_agent.usage is None:
            return None

        usage_copy = self._main_agent.usage.model_copy(deep=True)

        if self._throughput_tracked_tokens > 0:
            usage_copy.throughput_tps = self._throughput_weighted_sum / self._throughput_tracked_tokens
        else:
            usage_copy.throughput_tps = None

        if self._first_token_latency_count > 0:
            usage_copy.first_token_latency_ms = self._first_token_latency_sum / self._first_token_latency_count
        else:
            usage_copy.first_token_latency_ms = None

        usage_copy.cache_hit_rate = self.cache.avg_hit_rate

        return TaskMetadata(
            model_name=self._main_agent.model_name,
            provider=self._main_agent.provider,
            usage=usage_copy,
            task_duration_s=task_duration_s,
            turn_count=self._turn_count,
        )

    def get_partial_item(self, task_duration_s: float) -> TaskMetadataItem | None:
        """Return a snapshot of full metadata (main + sub-agents) without modifying state.

        Returns None if no usage data has been accumulated yet.
        """
        main_agent = self.get_partial(task_duration_s)
        if main_agent is None:
            return None

        return TaskMetadataItem(
            main_agent=main_agent,
            sub_agent_task_metadata=list(self._sub_agent_metadata),
        )

    def finalize(self, task_duration_s: float) -> TaskMetadataItem:
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

            self._main_agent.usage.cache_hit_rate = self.cache.avg_hit_rate

        self._main_agent.task_duration_s = task_duration_s
        self._main_agent.turn_count = self._turn_count
        return TaskMetadataItem(main_agent=self._main_agent, sub_agent_task_metadata=self._sub_agent_metadata)


@dataclass
class SessionContext:
    """Shared session-level context for task and turn execution.

    Contains common fields that both TaskExecutionContext and TurnExecutionContext need.
    """

    session_id: str
    work_dir: Path
    get_conversation_history: Callable[[], list[message.HistoryEvent]]
    append_history: Callable[[Sequence[message.HistoryEvent]], None]
    file_tracker: FileTracker
    file_change_summary: FileChangeSummary
    todo_context: TodoContext
    run_subtask: RunSubtask | None
    request_user_interaction: RequestUserInteraction | None


@dataclass
class TaskExecutionContext:
    """Execution context required to run a task."""

    session: Session
    session_ctx: SessionContext
    profile: AgentProfile
    tool_registry: dict[str, type[ToolABC]]
    sub_agent_state: SubAgentState | None
    # LLM client for compaction (uses main if not set)
    compact_llm_client: LLMClientABC | None = None
    apply_llm_client_change: Callable[[LLMClientABC], AgentProfile] | None = None


class TaskExecutor:
    """Executes a complete task (multiple turns until no more tool calls).

    Manages task-level state like metadata accumulation and retry logic.
    """

    def __init__(self, context: TaskExecutionContext) -> None:
        self._context = context
        self._current_turn: TurnExecutor | None = None
        self._started_at: float = 0.0
        self._metadata_accumulator: MetadataAccumulator | None = None
        self._rewind_manager: RewindManager | None = None
        self._handoff_manager: HandoffManager | None = None
        self._current_user_input_text: str | None = None
        self._task_visible_output_started = False
        self._last_interrupt_show_notice = True
        self._last_interrupt_prefill_text: str | None = None

    def _has_tool(self, tool_name: str) -> bool:
        return any(tool.name == tool_name for tool in self._context.profile.tools)

    @staticmethod
    def _developer_message_key(item: message.DeveloperMessage) -> str:
        return item.model_dump_json(exclude={"id", "created_at", "response_id"})

    async def _collect_and_append_attachments(
        self, *, skip_existing: bool = False
    ) -> list[events.DeveloperMessageEvent]:
        ctx = self._context
        attachment_results = await collect_attachments(ctx.session, ctx.profile.attachments)
        events_to_emit: list[events.DeveloperMessageEvent] = []
        existing: set[str] = set()
        if skip_existing:
            existing = {
                self._developer_message_key(item)
                for item in ctx.session.get_llm_history()
                if isinstance(item, message.DeveloperMessage)
            }
        for item in attachment_results:
            key = self._developer_message_key(item)
            if skip_existing and key in existing:
                continue
            ctx.session.append_history([item])
            existing.add(key)
            events_to_emit.append(events.DeveloperMessageEvent(session_id=ctx.session_ctx.session_id, item=item))
        return events_to_emit

    @property
    def last_interrupt_show_notice(self) -> bool:
        return self._last_interrupt_show_notice

    def take_interrupt_prefill_text(self) -> str | None:
        text = self._last_interrupt_prefill_text
        self._last_interrupt_prefill_text = None
        return text

    def get_partial_metadata(self) -> TaskMetadata | None:
        """Get the currently accumulated metadata without finalizing.

        Returns partial metadata that can be used if the task is interrupted.
        """
        if self._metadata_accumulator is None or self._started_at <= 0:
            return None
        task_duration_s = time.perf_counter() - self._started_at
        return self._metadata_accumulator.get_partial(task_duration_s)

    def _fallback_model(self, error_message: str) -> tuple[AgentProfile, events.FallbackModelConfigWarnEvent] | None:
        ctx = self._context
        client = ctx.profile.llm_client
        if not isinstance(client, FallbackLLMClient):
            return None
        if not _is_fallbackable_llm_error(error_message):
            return None

        fallback = client.fallback_to_next()
        if fallback is None:
            return None

        if ctx.apply_llm_client_change is not None:
            new_profile = ctx.apply_llm_client_change(client)
        else:
            new_profile = AgentProfile(
                llm_client=client,
                system_prompt=ctx.profile.system_prompt,
                tools=ctx.profile.tools,
                attachments=ctx.profile.attachments,
            )
        ctx.profile = new_profile
        ctx.tool_registry = _build_tool_registry(new_profile.tools)

        sub_agent_type = ctx.sub_agent_state.sub_agent_type if ctx.sub_agent_state is not None else None
        reason = _fallback_reason(error_message)
        entry = message.FallbackModelConfigWarnEntry(
            sub_agent_type=sub_agent_type,
            from_model=fallback.from_candidate.model_name,
            from_provider=fallback.from_candidate.provider,
            to_model=fallback.to_candidate.model_name,
            to_provider=fallback.to_candidate.provider,
            reason=reason,
        )
        ctx.session_ctx.append_history([entry])
        event = events.FallbackModelConfigWarnEvent(
            session_id=ctx.session_ctx.session_id,
            sub_agent_type=entry.sub_agent_type,
            from_model=entry.from_model,
            from_provider=entry.from_provider,
            to_model=entry.to_model,
            to_provider=entry.to_provider,
            reason=entry.reason,
        )
        return new_profile, event

    def on_interrupt(self) -> list[events.Event]:
        """Handle an interrupt by finalizing the current turn and emitting partial metadata.

        This method synthesizes best-effort UI/history events for an interrupted
        task, but it does not cancel the outer asyncio task.
        """
        ui_events: list[events.Event] = []
        had_aborted_assistant_message = False
        history_len_before = len(self._context.session.conversation_history)
        show_notice = self._task_visible_output_started
        if self._current_turn is not None:
            show_notice = show_notice or getattr(self._current_turn, "should_show_interrupt_notice", True)
            for evt in self._current_turn.on_interrupt():
                # Collect sub-agent task metadata from cancelled tool results
                if (
                    isinstance(evt, events.ToolResultEvent)
                    and evt.task_metadata is not None
                    and self._metadata_accumulator is not None
                ):
                    self._metadata_accumulator.add_sub_agent_metadata(evt.task_metadata)
                ui_events.append(evt)
            self._current_turn = None

            new_items = self._context.session.conversation_history[history_len_before:]
            had_aborted_assistant_message = any(
                isinstance(item, message.AssistantMessage) and item.stop_reason == "aborted" for item in new_items
            )

        self._last_interrupt_show_notice = show_notice
        if not show_notice and self._current_user_input_text and self._current_user_input_text.strip():
            self._last_interrupt_prefill_text = self._current_user_input_text
        else:
            self._last_interrupt_prefill_text = None

        if not had_aborted_assistant_message:
            self._context.session_ctx.append_history([message.InterruptEntry(show_notice=show_notice)])

        # Emit partial metadata on cancellation
        if self._metadata_accumulator is not None and self._started_at > 0:
            task_duration_s = time.perf_counter() - self._started_at
            accumulated = self._metadata_accumulator.get_partial_item(task_duration_s)
            if accumulated is not None:
                accumulated.is_partial = True
                session_id = self._context.session_ctx.session_id
                ui_events.append(events.TaskMetadataEvent(metadata=accumulated, session_id=session_id, is_partial=True))
                self._context.session_ctx.append_history([accumulated])

        return ui_events

    async def run(self, user_input: message.UserInputPayload) -> AsyncGenerator[events.Event]:
        """Execute the task, yielding events as they occur."""
        ctx = self._context
        session_ctx = ctx.session_ctx
        self._started_at = time.perf_counter()
        self._current_user_input_text = user_input.text
        self._task_visible_output_started = False
        self._last_interrupt_show_notice = True
        self._last_interrupt_prefill_text = None
        has_user_input = bool(user_input.text.strip() or user_input.images)

        if ctx.sub_agent_state is None:
            if self._has_tool(tools.REWIND):
                self._rewind_manager = RewindManager()
                self._rewind_manager.set_n_checkpoints(ctx.session.n_checkpoints)
                self._rewind_manager.sync_checkpoints(ctx.session.get_checkpoint_user_messages())
            self._handoff_manager = HandoffManager()

        yield events.TaskStartEvent(
            session_id=session_ctx.session_id,
            sub_agent_state=ctx.sub_agent_state,
            model_id=ctx.profile.llm_client.get_llm_config().model_id,
        )
        del user_input  # Persisted by the operation handler before launching the task.

        profile = ctx.profile
        self._metadata_accumulator = MetadataAccumulator(model_name=profile.llm_client.model_name)
        metadata_accumulator = self._metadata_accumulator

        if self._rewind_manager is not None and has_user_input:
            checkpoint_id = ctx.session.create_checkpoint()
            self._rewind_manager.set_n_checkpoints(ctx.session.n_checkpoints)
            user_msg = ctx.session.get_user_message_before_checkpoint(checkpoint_id) or ""
            self._rewind_manager.register_checkpoint(checkpoint_id, user_msg)

        skip_threshold_compaction = False
        empty_response_retries = 0

        while True:
            # Threshold-based compaction before starting a new turn.
            # This matters for multi-turn tool loops where no new user input occurs.
            if (
                ctx.sub_agent_state is None
                and not skip_threshold_compaction
                and should_compact_threshold(
                    session=ctx.session,
                    config=None,
                    llm_config=profile.llm_client.get_llm_config(),
                )
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
                        main_profile=profile,
                    )
                    log_debug("[Compact] result", str(result.to_entry()), debug_type=DebugType.RESPONSE)

                    _reset_attachment_loaded_flags(ctx.session.file_tracker)
                    session_ctx.append_history([result.to_entry()])
                    if self._rewind_manager is not None:
                        self._rewind_manager.set_n_checkpoints(ctx.session.n_checkpoints)
                        self._rewind_manager.sync_checkpoints(ctx.session.get_checkpoint_user_messages())
                    metadata_accumulator.cache.notify_compaction()
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
                    if result.fork_event is not None:
                        yield result.fork_event
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

                    nothing_to_compact = isinstance(e, ValueError) and str(e).startswith("Nothing to compact")
                    if not nothing_to_compact:
                        skip_threshold_compaction = True

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
                    if not nothing_to_compact:
                        yield events.ErrorEvent(
                            error_message=f"Compaction failed, continuing without compaction: {e}",
                            can_retry=True,
                            session_id=session_ctx.session_id,
                        )

            # Process attachments in parallel with error isolation after compaction
            # resets transient loaded flags.
            for event in await self._collect_and_append_attachments():
                yield event

            turn: TurnExecutor | None = None
            turn_succeeded = False
            last_error_message: str | None = None
            failed_attempts = 0

            while failed_attempts <= MAX_FAILED_TURN_RETRIES:
                turn_context = TurnExecutionContext(
                    session_ctx=session_ctx,
                    llm_client=profile.llm_client,
                    system_prompt=profile.system_prompt,
                    tools=profile.tools,
                    tool_registry=ctx.tool_registry,
                    sub_agent_state=ctx.sub_agent_state,
                    rewind_manager=self._rewind_manager,
                    handoff_manager=self._handoff_manager,
                    prev_turn_input_tokens=metadata_accumulator.prev_turn_input_tokens,
                )

                metadata_accumulator.cache.record_pre_call_state(
                    profile.system_prompt, profile.tools, profile.llm_client.model_name
                )
                turn = TurnExecutor(turn_context)
                self._current_turn = turn

                try:
                    async for e in turn.run():
                        match e:
                            case events.AssistantTextDeltaEvent() if e.content:
                                self._task_visible_output_started = True
                            case events.ResponseCompleteEvent() if e.content:
                                self._task_visible_output_started = True
                            case events.ToolCallStartEvent() | events.ToolCallEvent() | events.ToolResultEvent():
                                self._task_visible_output_started = True
                            case events.ToolOutputDeltaEvent() if e.content:
                                self._task_visible_output_started = True
                            case _:
                                pass
                        match e:
                            case events.ResponseCompleteEvent() as am:
                                yield am
                            case events.UsageEvent() as e:
                                cache_break = metadata_accumulator.add(e.usage)
                                yield e
                                if metadata_accumulator.last_turn_cache_hit_rate is not None:
                                    cache_hit_entry = message.CacheHitRateEntry(
                                        cache_hit_rate=metadata_accumulator.last_turn_cache_hit_rate,
                                        cached_tokens=metadata_accumulator.last_turn_cached_tokens,
                                        prev_turn_input_tokens=metadata_accumulator.last_turn_prev_input_tokens,
                                    )
                                    session_ctx.append_history([cache_hit_entry])
                                    yield events.CacheHitRateEvent(
                                        session_id=session_ctx.session_id,
                                        cache_hit_rate=metadata_accumulator.last_turn_cache_hit_rate,
                                        cached_tokens=metadata_accumulator.last_turn_cached_tokens,
                                        prev_turn_input_tokens=metadata_accumulator.last_turn_prev_input_tokens,
                                    )
                                if cache_break is not None:
                                    try:
                                        report_path = cache_break.write_report()
                                        msg = cache_break.format_message(report_path)
                                    except OSError:
                                        msg = cache_break.format_message()
                                    yield events.ErrorEvent(
                                        session_id=session_ctx.session_id,
                                        error_message=msg,
                                        can_retry=True,
                                    )
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
                                main_profile=profile,
                            )
                            log_debug(
                                "[Compact:Overflow] result", str(result.to_entry()), debug_type=DebugType.RESPONSE
                            )
                            _reset_attachment_loaded_flags(ctx.session.file_tracker)
                            session_ctx.append_history([result.to_entry()])
                            if self._rewind_manager is not None:
                                self._rewind_manager.set_n_checkpoints(ctx.session.n_checkpoints)
                                self._rewind_manager.sync_checkpoints(ctx.session.get_checkpoint_user_messages())
                            metadata_accumulator.cache.notify_compaction()
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
                            if result.fork_event is not None:
                                yield result.fork_event
                            for event in await self._collect_and_append_attachments(skip_existing=True):
                                yield event
                            failed_attempts += 1
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
                            yield events.CompactionEndEvent(
                                session_id=session_ctx.session_id,
                                reason=CompactionReason.OVERFLOW.value,
                                aborted=True,
                                will_retry=False,
                            )
                            error_message = (
                                f"{last_error_message}\nCompaction failed while recovering from context overflow: {exc}"
                            )
                            yield events.ErrorEvent(
                                error_message=error_message,
                                can_retry=False,
                                session_id=session_ctx.session_id,
                            )
                            if ctx.sub_agent_state is not None:
                                raise RuntimeError(error_message) from exc
                            return

                    fallback_result = self._fallback_model(last_error_message)
                    if fallback_result is not None:
                        profile, fallback_event = fallback_result
                        metadata_accumulator.cache.notify_compaction()
                        failed_attempts = 0
                        yield fallback_event
                        continue
                    if _is_fallbackable_llm_error(last_error_message):
                        break

                    if failed_attempts < MAX_FAILED_TURN_RETRIES:
                        retry_number = failed_attempts + 1
                        delay = _retry_delay_seconds(retry_number)
                        error_msg = f"Retrying {retry_number}/{MAX_FAILED_TURN_RETRIES} in {delay:.1f}s"
                        if last_error_message:
                            error_msg = f"{error_msg} - {last_error_message}"
                        yield events.ErrorEvent(
                            error_message=error_msg, can_retry=True, session_id=session_ctx.session_id
                        )
                        failed_attempts += 1
                        await asyncio.sleep(delay)
                        continue
                    break
                finally:
                    self._current_turn = None

            if not turn_succeeded:
                log_debug(
                    "Maximum consecutive failed turns reached, aborting task",
                    debug_type=DebugType.EXECUTION,
                )
                final_error = (
                    "Turn failed after model fallback candidates were exhausted."
                    if last_error_message and _is_fallbackable_llm_error(last_error_message)
                    else f"Turn failed after {MAX_FAILED_TURN_RETRIES} retries."
                )
                if last_error_message:
                    final_error = f"{last_error_message}\n{final_error}"
                yield events.ErrorEvent(error_message=final_error, can_retry=False, session_id=session_ctx.session_id)
                return

            if self._rewind_manager is not None:
                pending = self._rewind_manager.fetch_pending()
                if pending is not None:
                    try:
                        entry = ctx.session.revert_to_checkpoint(pending.checkpoint_id, pending.note, pending.rationale)
                    except ValueError as exc:
                        yield events.ErrorEvent(
                            error_message=str(exc),
                            can_retry=False,
                            session_id=session_ctx.session_id,
                        )
                    else:
                        messages_discarded = entry.reverted_from_index - len(ctx.session.conversation_history)
                        session_ctx.append_history([entry])
                        self._rewind_manager.set_n_checkpoints(ctx.session.n_checkpoints)
                        self._rewind_manager.sync_checkpoints(ctx.session.get_checkpoint_user_messages())
                        metadata_accumulator.cache.notify_compaction()
                        yield events.RewindEvent(
                            session_id=session_ctx.session_id,
                            checkpoint_id=pending.checkpoint_id,
                            note=pending.note,
                            rationale=pending.rationale,
                            original_user_message=entry.original_user_message,
                            messages_discarded=messages_discarded,
                        )
                        continue

            if self._handoff_manager is not None:
                pending_handoff = self._handoff_manager.fetch_pending()
                if pending_handoff is not None:
                    yield events.CompactionStartEvent(
                        session_id=session_ctx.session_id,
                        reason="handoff",
                    )
                    try:
                        log_debug("[Handoff] start", debug_type=DebugType.RESPONSE)
                        compact_client = ctx.compact_llm_client or profile.llm_client
                        result = await run_handoff(
                            session=ctx.session,
                            goal=pending_handoff.goal,
                            llm_client=compact_client,
                            llm_config=compact_client.get_llm_config(),
                            main_profile=profile,
                        )
                        log_debug("[Handoff] result", str(result.to_entry()), debug_type=DebugType.RESPONSE)
                        _reset_attachment_loaded_flags(ctx.session.file_tracker)
                        session_ctx.append_history([result.to_entry()])
                        if self._rewind_manager is not None:
                            self._rewind_manager.set_n_checkpoints(ctx.session.n_checkpoints)
                            self._rewind_manager.sync_checkpoints(ctx.session.get_checkpoint_user_messages())
                        metadata_accumulator.cache.notify_compaction()
                        yield events.CompactionEndEvent(
                            session_id=session_ctx.session_id,
                            reason="handoff",
                            aborted=False,
                            will_retry=False,
                            tokens_before=result.tokens_before,
                            kept_from_index=result.first_kept_index,
                            summary=result.summary,
                            kept_items_brief=result.kept_items_brief,
                        )
                        if result.fork_event is not None:
                            yield result.fork_event
                        continue
                    except asyncio.CancelledError:
                        yield events.CompactionEndEvent(
                            session_id=session_ctx.session_id,
                            reason="handoff",
                            aborted=True,
                            will_retry=False,
                        )
                        raise
                    except Exception as e:
                        import traceback

                        log_debug(
                            "[Handoff] error",
                            str(e.__class__.__name__),
                            str(e),
                            traceback.format_exc(),
                            debug_type=DebugType.RESPONSE,
                        )
                        yield events.CompactionEndEvent(
                            session_id=session_ctx.session_id,
                            reason="handoff",
                            aborted=True,
                            will_retry=False,
                        )
                        yield events.ErrorEvent(
                            error_message=f"Handoff failed: {e}",
                            can_retry=False,
                            session_id=session_ctx.session_id,
                        )
                        return

            if turn is None or turn.task_finished:
                # Empty response (no text, no tool calls): often caused by transient
                # provider issues returning an empty stream. Inject a continuation
                # prompt so the model can resume or explicitly signal completion
                # with a final response, rather than silently ending the task.
                if (
                    turn is not None
                    and turn.continue_agent
                    and not turn.task_result.strip()
                    and empty_response_retries < MAX_EMPTY_RESPONSE_RETRIES
                ):
                    empty_response_retries += 1
                    log_debug(
                        "[EmptyResponse] injecting continuation prompt",
                        f"attempt {empty_response_retries}/{MAX_EMPTY_RESPONSE_RETRIES}",
                        debug_type=DebugType.RESPONSE,
                    )
                    yield events.ErrorEvent(
                        error_message=(
                            f"Empty response from model, retrying {empty_response_retries}/{MAX_EMPTY_RESPONSE_RETRIES}"
                        ),
                        can_retry=True,
                        session_id=session_ctx.session_id,
                    )
                    session_ctx.append_history(
                        [message.UserMessage(parts=[message.TextPart(text=EMPTY_RESPONSE_CONTINUATION_PROMPT)])]
                    )
                    continue
                break
            empty_response_retries = 0

        # Finalize metadata
        task_duration_s = time.perf_counter() - self._started_at
        accumulated = metadata_accumulator.finalize(task_duration_s)

        is_partial_metadata = turn is not None and not turn.continue_agent
        accumulated.is_partial = is_partial_metadata
        yield events.TaskMetadataEvent(
            metadata=accumulated, session_id=session_ctx.session_id, is_partial=is_partial_metadata
        )
        session_ctx.append_history([accumulated])

        # Get task result from turn
        task_result = turn.task_result if turn is not None else ""

        yield events.TaskFinishEvent(
            session_id=session_ctx.session_id,
            task_result=task_result,
        )


def _reset_attachment_loaded_flags(file_tracker: dict[str, FileStatus]) -> None:
    reset_attachment_loaded_flags(file_tracker)


def _build_tool_registry(tool_schemas: list[llm_param.ToolSchema]) -> dict[str, type[ToolABC]]:
    available_tool_names = {tool.name for tool in tool_schemas}
    return {name: tool_class for name, tool_class in get_registry().items() if name in available_tool_names}


def _retry_delay_seconds(attempt: int) -> float:
    """Compute exponential backoff delay for the given attempt count."""
    capped_attempt = max(1, attempt)
    delay = INITIAL_RETRY_DELAY_S * (2 ** (capped_attempt - 1))
    return min(delay, MAX_RETRY_DELAY_S)


def _fallback_reason(error_message: str) -> str:
    first_line = error_message.strip().splitlines()[0] if error_message.strip() else "LLM request failed"
    return first_line[:500]


def _is_fallbackable_llm_error(error_message: str) -> bool:
    text = error_message.casefold()
    if is_context_overflow(error_message):
        return False
    fallbackable_markers = (
        "insufficient_quota",
        "exceeded your current quota",
        "quota exceeded",
        "quota_exceeded",
        "billing",
        "credit balance",
        "credits exhausted",
        "insufficient credits",
        "payment required",
        "model_not_found",
        "model_not_available",
        "does not have access to model",
        "not authorized to access",
        "permission_denied",
        "permission denied",
        "usage_limit_reached",
    )
    return any(marker in text for marker in fallbackable_markers)
