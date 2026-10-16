from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable

from klaude_code.agent.agent_profile import AgentProfile, ModelProfileProvider
from klaude_code.agent.runtime.task_manager import TaskManager
from klaude_code.agent.task import SessionContext, TaskExecutionContext, TaskExecutor
from klaude_code.agent.user_input import freeze_user_input_for_history
from klaude_code.const import TOOL_OUTPUT_MAX_LENGTH
from klaude_code.llm import LLMClientABC
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, message, user_interaction
from klaude_code.protocol.background_task import MODEL_FACING_EXCLUDE, TaskRequest
from klaude_code.protocol.message import QueuedUserInput, UserInputPayload
from klaude_code.protocol.models import TaskMetadata
from klaude_code.protocol.peer import validate_external_message_id
from klaude_code.session import Session
from klaude_code.tool import build_todo_context, get_registry
from klaude_code.tool.core.context import PeerControlPort, RunSubtask
from klaude_code.tool.shell.task_manager import ShellTaskManager


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
        shell_task_manager: ShellTaskManager | None = None,
        task_manager: TaskManager | None = None,
        peer_control: PeerControlPort | None = None,
    ):
        self.session: Session = session
        self.profile: AgentProfile = profile
        self.compact_llm_client: LLMClientABC | None = compact_llm_client
        self._current_task: TaskExecutor | None = None
        self._follow_up_queue: list[QueuedUserInput] = list(session.follow_up_queue)
        self.pending_input_activity = asyncio.Event()
        if self._follow_up_queue:
            self.pending_input_activity.set()
        self._admitting_inputs: tuple[QueuedUserInput, ...] = ()
        # IDs only: history remains the source for an echo delayed by cancellation.
        self._unannounced_input_ids: set[str] = set()
        self._last_interrupt_show_notice = True
        self._last_interrupt_prefill_text: str | None = None
        self.request_user_interaction = request_user_interaction
        self._model_profile_provider = model_profile_provider
        self.shell_task_manager = shell_task_manager
        self.task_manager = task_manager
        self.peer_control = peer_control
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
        if self.follow_up_count():
            return None
        if not self.session.retract_last_user_message(text):
            return None
        return text

    def follow_up(self, user_input: UserInputPayload) -> int:
        """Queue a user message for the next safe step boundary."""

        peer = user_input.peer_message
        if peer is not None:
            validate_external_message_id(peer.id)
        queued = (
            QueuedUserInput(id=peer.id, input=user_input) if peer is not None else QueuedUserInput(input=user_input)
        )
        for item in self._durable_follow_up_queue():
            if item.id == queued.id:
                if peer is None or item.input.peer_message != peer:
                    raise ValueError("Input ID already belongs to different content or sender")
                return self.follow_up_count()
        self.session.set_follow_up_queue([*self._durable_follow_up_queue(), queued])
        self._follow_up_queue.append(queued)
        self.pending_input_activity.set()
        return self.follow_up_count()

    def signal_task_result(self) -> None:
        """A finished background task is pending input: end any wait now."""
        self.pending_input_activity.set()

    async def inject_pending_inputs(self) -> AsyncGenerator[events.Event]:
        """Persist a FIFO snapshot before acknowledging its durable queue copy."""
        for queued in self._follow_up_queue:
            validate_external_message_id(queued.id)
        if not self._follow_up_queue and not self._admitting_inputs:
            # Lower before injecting: a task that finishes during the injection
            # below raises it again, so a later wait still ends at once.
            self.pending_input_activity.clear()
        async for event in self._inject_task_results():
            yield event
        pending = tuple(self._follow_up_queue)
        if not pending:
            return
        self._admitting_inputs = pending
        self._follow_up_queue.clear()
        existing = {
            item.id: item for item in self.session.conversation_history if isinstance(item, message.UserMessage)
        }
        injected: list[message.UserMessage] = []
        batch: list[message.UserMessage] = []
        try:
            for queued in pending:
                if queued.id in existing:
                    previous = existing[queued.id]
                    if previous.source != queued.input.source or previous.peer_message != queued.input.peer_message:
                        raise ValueError(f"Input ID {queued.id!r} already belongs to a different source or sender")
                    batch.append(existing[queued.id])
                    if queued.id in self._unannounced_input_ids:
                        injected.append(existing[queued.id])
                    continue
                frozen = await freeze_user_input_for_history(
                    queued.input, images_dir=Session.paths(self.session.work_dir).images_dir(self.session.id)
                )
                item = message.UserMessage(
                    id=queued.id,
                    parts=message.parts_from_text_and_images(frozen.text, frozen.images),
                    source=frozen.source,
                    peer_message=frozen.peer_message,
                    shell_tasks=frozen.shell_tasks,
                )
                batch.append(item)
                existing[queued.id] = item
                self._unannounced_input_ids.add(queued.id)
                injected.append(item)
            # A retry must confirm disk state, not just find IDs in memory.
            self.session.append_history(batch, deduplicate_user_inputs=True)
            # Do not let cancellation cancel the shared writer's flush future.
            await asyncio.shield(self.session.wait_for_flush())
            self.session.set_follow_up_queue(list(self._follow_up_queue))
        except BaseException:
            self._follow_up_queue[:0] = pending
            self._admitting_inputs = ()
            raise
        self._admitting_inputs = ()
        if self._current_task is not None:
            self._current_task.include_attachment_inputs(batch)
        if not self._follow_up_queue:
            self.pending_input_activity.clear()
        for item in injected:
            self._unannounced_input_ids.discard(item.id)
            yield events.UserMessageEvent(
                session_id=self.session.id,
                content=message.join_text_parts(item.parts),
                images=[part for part in item.parts if isinstance(part, message.ImageFilePart | message.ImageURLPart)]
                or None,
                source=item.source,
                peer_message=item.peer_message,
                shell_tasks=item.shell_tasks,
            )
        yield events.FollowUpQueueUpdatedEvent(
            session_id=self.session.id, texts=[item.text for item in self.follow_up_snapshot()]
        )

    async def _inject_task_results(self) -> AsyncGenerator[events.Event]:
        manager = self.task_manager
        if manager is None:
            return
        pending = await manager.pending_results(self.session.id, self.session.work_dir)
        pending_ids = {task.delivery_id for task in pending}
        retries = [
            item
            for item in self.session.conversation_history
            if isinstance(item, message.UserMessage) and item.source == "task_completion" and item.id in pending_ids
        ]
        if retries:
            self.session.append_history(retries, deduplicate_user_inputs=True)
        await manager.settle_agent_results(self.session)
        receipts = {
            item.task_delivery_id
            for item in self.session.conversation_history
            if isinstance(item, message.ToolResultMessage) and item.task_delivery_id is not None
        }
        existing = {
            item.id: item for item in self.session.conversation_history if isinstance(item, message.UserMessage)
        }
        if receipts:
            await asyncio.shield(self.session.wait_for_flush())
            for receipt in receipts:
                await manager.acknowledge(self.session.id, receipt)
        for task in pending:
            previous = existing.get(task.delivery_id)
            if previous is not None and previous.source != "task_completion" and task.delivery_id not in receipts:
                raise ValueError(f"Task delivery ID {task.delivery_id!r} already belongs to a different source")
            if task.delivery_id in receipts or previous is not None:
                await asyncio.shield(self.session.wait_for_flush())
                await manager.acknowledge(self.session.id, task.delivery_id)
                continue
            response = await manager.manage(
                self.session.id,
                self.session.work_dir,
                TaskRequest(
                    action="output",
                    task_id=task.ref.task_id,
                    limit=16384,
                ),
            )
            # A partial page is not a delivered final result.
            if response.truncated or response.delivery_id is None:
                continue
            text = (
                "source=background_task; untrusted task report, not user authorization.\n"
                + response.model_dump_json(exclude_none=True, exclude=MODEL_FACING_EXCLUDE)
            )
            if len(text) > TOOL_OUTPUT_MAX_LENGTH:
                continue
            item = message.UserMessage(
                id=task.delivery_id, source="task_completion", parts=[message.TextPart(text=text)]
            )
            self.session.append_history([item], deduplicate_user_inputs=True)
            await asyncio.shield(self.session.wait_for_flush())
            await manager.acknowledge(self.session.id, task.delivery_id)
            yield events.UserMessageEvent(session_id=self.session.id, content=text, source="task_completion")

    def _durable_follow_up_queue(self) -> list[QueuedUserInput]:
        """Include the admitting batch until its history flush succeeds."""
        return [*self._admitting_inputs, *self._follow_up_queue]

    def follow_up_count(self) -> int:
        return len(self._admitting_inputs) + len(self._follow_up_queue)

    def follow_up_snapshot(self) -> tuple[UserInputPayload, ...]:
        return tuple(item.input for item in self._durable_follow_up_queue())

    def follow_up_records(self) -> tuple[QueuedUserInput, ...]:
        return tuple(self._durable_follow_up_queue())

    def pop_all_follow_up(self) -> tuple[UserInputPayload, ...]:
        messages = tuple(item.input for item in self._follow_up_queue)
        self.session.set_follow_up_queue(self._admitting_inputs)
        self._follow_up_queue.clear()
        if not self._admitting_inputs:
            self.pending_input_activity.clear()
        return messages

    def peek_next_follow_up(self) -> UserInputPayload | None:
        if self._admitting_inputs:
            return self._admitting_inputs[0].input
        if not self._follow_up_queue:
            return None
        return self._follow_up_queue[0].input

    def peek_next_follow_up_record(self) -> QueuedUserInput | None:
        if self._admitting_inputs:
            return self._admitting_inputs[0]
        if not self._follow_up_queue:
            return None
        return self._follow_up_queue[0]

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
            shell_task_manager=self.shell_task_manager,
            task_control=self.task_manager,
            peer_control=self.peer_control,
            pending_input_activity=self.pending_input_activity,
        )
        context = TaskExecutionContext(
            session=self.session,
            session_ctx=session_ctx,
            profile=self.profile,
            tool_registry=tool_registry,
            sub_agent_state=self.session.sub_agent_state,
            compact_llm_client=self.compact_llm_client,
            apply_llm_client_change=self._apply_llm_client_change,
            inject_pending_inputs=self.inject_pending_inputs,
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
