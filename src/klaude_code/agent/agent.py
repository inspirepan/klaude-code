from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable

from klaude_code.agent.agent_profile import AgentProfile, ModelProfileProvider
from klaude_code.agent.task import SessionContext, TaskExecutionContext, TaskExecutor
from klaude_code.llm import LLMClientABC
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, user_interaction
from klaude_code.protocol.message import UserInputPayload
from klaude_code.protocol.models import TaskMetadata
from klaude_code.session import Session
from klaude_code.tool import build_todo_context, get_registry
from klaude_code.tool.core.context import RunSubtask


class Agent:
    def __init__(
        self,
        session: Session,
        profile: AgentProfile,
        compact_llm_client: LLMClientABC | None = None,
        request_user_interaction: (
            Callable[
                [
                    str,
                    user_interaction.UserInteractionSource,
                    user_interaction.UserInteractionRequestPayload,
                    str | None,
                ],
                Awaitable[user_interaction.UserInteractionResponse],
            ]
            | None
        ) = None,
        model_profile_provider: ModelProfileProvider | None = None,
    ):
        self.session: Session = session
        self.profile: AgentProfile = profile
        self.compact_llm_client: LLMClientABC | None = compact_llm_client
        self._current_task: TaskExecutor | None = None
        self._follow_up_queue: list[QueuedUserInput] = list(session.follow_up_queue)
        # Head popped by begin_follow_up but not yet confirmed durable by
        # acknowledge_follow_up; kept out of snapshots, kept in the persisted
        # queue (a crash in between re-runs it, deduped by turn id).
        self._in_flight_follow_up: QueuedUserInput | None = None
        self._last_interrupt_show_notice = True
        self._last_interrupt_prefill_text: str | None = None
        self.request_user_interaction = request_user_interaction
        self._model_profile_provider = model_profile_provider
        if not self.session.model_name:
            self.session.model_name = profile.llm_client.model_name

    @property
    def last_interrupt_show_notice(self) -> bool:
        return self._last_interrupt_show_notice

    def consume_interrupt_prefill_text(self) -> str | None:
        text = self._last_interrupt_prefill_text
        self._last_interrupt_prefill_text = None
        return text

    def retract_interrupted_user_message(self) -> str | None:
        """Withdraw the just-interrupted turn's user message from history.

        Only valid right after ``on_interrupt`` armed the prefill text (the
        turn produced no visible output). The prefill stays armed — the
        frontend that requested retraction restores it into its input box.
        Skipped when follow-ups are queued: the TUI drops the prefill in that
        case, so keeping the message in history is the only lossless choice.
        """
        text = self._last_interrupt_prefill_text
        if text is None:
            return None
        if self.session.sub_agent_state is not None:
            return None
        if self._follow_up_queue:
            return None
        if not self.session.retract_last_user_message(text):
            return None
        return text

    def follow_up(self, user_input: UserInputPayload) -> int:
        """Queue a user message to run after the active task completes."""

        self._follow_up_queue.append(QueuedUserInput(input=user_input))
        self.session.set_follow_up_queue(self._durable_follow_up_queue())
        return len(self._follow_up_queue)

    def _durable_follow_up_queue(self) -> list[QueuedUserInput]:
        """The queue as persisted: includes the in-flight head until acked."""
        if self._in_flight_follow_up is not None:
            return [self._in_flight_follow_up, *self._follow_up_queue]
        return list(self._follow_up_queue)

    def follow_up_count(self) -> int:
        return len(self._follow_up_queue)

    def follow_up_snapshot(self) -> tuple[UserInputPayload, ...]:
        return tuple(self._follow_up_queue)

    def pop_all_follow_up(self) -> tuple[UserInputPayload, ...]:
        messages = tuple(self._follow_up_queue)
        self._follow_up_queue.clear()
        self.session.set_follow_up_queue(self._durable_follow_up_queue())
        return messages

    def peek_next_follow_up(self) -> UserInputPayload | None:
        if not self._follow_up_queue:
            return None
        return self._follow_up_queue[0]

    def pop_next_follow_up(self) -> UserInputPayload | None:
        if not self._follow_up_queue:
            return None
        queued = self._follow_up_queue.pop(0)
        self.session.set_follow_up_queue(self._durable_follow_up_queue())
        return queued.input

    def begin_follow_up(self, item_id: str) -> bool:
        """Two-phase pop, phase 1: drop the head from the in-memory queue.

        Snapshots (queue UI events, session_info) stop showing the message the
        moment its turn is submitted. The durable copy in session meta keeps
        it until acknowledge_follow_up confirms the turn reached history — a
        crash in between re-runs it on restore, deduped by turn id.
        """
        if not self._follow_up_queue or self._follow_up_queue[0].id != item_id:
            return False
        self._in_flight_follow_up = self._follow_up_queue.pop(0)
        return True

    def acknowledge_follow_up(self, item_id: str, *, next_enqueued_at: float | None = None) -> bool:
        if self._in_flight_follow_up is not None and self._in_flight_follow_up.id == item_id:
            self._in_flight_follow_up = None
        elif self._follow_up_queue and self._follow_up_queue[0].id == item_id:
            # Legacy single-phase path: begin_follow_up was not called.
            self._follow_up_queue.pop(0)
        else:
            return False
        if self._follow_up_queue and next_enqueued_at is not None:
            self._follow_up_queue[0].enqueued_at = next_enqueued_at
        self.session.set_follow_up_queue(self._durable_follow_up_queue())
        return True

    def on_interrupt(self) -> Iterable[events.Event]:
        """Handle an interrupt by emitting best-effort cleanup events.

        This does not stop the running asyncio task by itself. The executor still
        needs to cancel the owning asyncio.Task to inject asyncio.CancelledError.
        """

        self._last_interrupt_show_notice = True
        self._last_interrupt_prefill_text = None
        if self._current_task is not None:
            yield from self._current_task.on_interrupt()
            self._last_interrupt_show_notice = self._current_task.last_interrupt_show_notice
            self._last_interrupt_prefill_text = self._current_task.take_interrupt_prefill_text()
            self._current_task = None

        log_debug(
            f"Session {self.session.id} interrupted",
            debug_type=DebugType.EXECUTION,
        )

    async def run_task(
        self, user_input: UserInputPayload, *, run_subtask: RunSubtask | None = None
    ) -> AsyncGenerator[events.Event]:
        available_tool_names = {tool.name for tool in self.profile.tools}
        tool_registry = {
            name: tool_class for name, tool_class in get_registry().items() if name in available_tool_names
        }

        session_ctx = SessionContext(
            session_id=self.session.id,
            work_dir=self.session.work_dir,
            get_conversation_history=self.session.get_llm_history,
            append_history=self.session.append_history,
            file_tracker=self.session.file_tracker,
            file_change_summary=self.session.file_change_summary,
            todo_context=build_todo_context(self.session),
            run_subtask=run_subtask,
            request_user_interaction=self.request_user_interaction,
            prompt_cache_key=self.session.prompt_cache_key,
        )
        context = TaskExecutionContext(
            session=self.session,
            session_ctx=session_ctx,
            profile=self.profile,
            tool_registry=tool_registry,
            sub_agent_state=self.session.sub_agent_state,
            compact_llm_client=self.compact_llm_client,
            apply_llm_client_change=self._apply_llm_client_change,
        )

        task = TaskExecutor(context)
        self._current_task = task

        try:
            async for event in task.run(user_input):
                yield event
        finally:
            self._current_task = None

    async def replay_history(self) -> AsyncGenerator[events.Event]:
        """Yield UI events reconstructed from saved conversation history."""

        if not self.session.conversation_history:
            return

        yield events.ReplayHistoryEvent(
            events=list(self.session.get_history_item()),
            updated_at=self.session.updated_at,
            session_id=self.session.id,
        )

    def set_model_profile(self, profile: AgentProfile) -> None:
        """Apply a fully constructed profile to the agent."""

        self.profile = profile
        self.session.model_name = profile.llm_client.model_name

    def _apply_llm_client_change(self, llm_client: LLMClientABC) -> AgentProfile:
        if self._model_profile_provider is None or (
            self.session.sub_agent_state is not None and self.session.sub_agent_state.fork_context
        ):
            profile = AgentProfile(
                llm_client=llm_client,
                system_prompt=self.profile.system_prompt,
                tools=self.profile.tools,
                attachments=self.profile.attachments,
            )
        else:
            sub_agent_type = None
            if self.session.sub_agent_state is not None and not self.session.sub_agent_state.fork_context:
                sub_agent_type = self.session.sub_agent_state.sub_agent_type
            profile = self._model_profile_provider.build_profile(
                llm_client,
                sub_agent_type,
                work_dir=self.session.work_dir,
            )
        self.set_model_profile(profile)
        return profile

    def get_llm_client(self) -> LLMClientABC:
        return self.profile.llm_client

    def get_partial_metadata(self) -> TaskMetadata | None:
        """Get partial metadata from the currently running task.

        Returns None if no task is running or no usage data has been accumulated.
        """
        if self._current_task is None:
            return None
        return self._current_task.get_partial_metadata()
