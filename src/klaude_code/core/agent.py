from __future__ import annotations

from collections.abc import AsyncGenerator, Iterable

from klaude_code.core.agent_profile import AgentProfile, Reminder
from klaude_code.core.task import SessionContext, TaskExecutionContext, TaskExecutor
from klaude_code.core.tool import build_todo_context, get_registry
from klaude_code.core.tool.context import RunSubtask
from klaude_code.llm import LLMClientABC
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, model
from klaude_code.protocol.message import UserInputPayload
from klaude_code.session import Session


class Agent:
    def __init__(
        self,
        session: Session,
        profile: AgentProfile,
        compact_llm_client: LLMClientABC | None = None,
    ):
        self.session: Session = session
        self.profile: AgentProfile = profile
        self.compact_llm_client: LLMClientABC | None = compact_llm_client
        self._current_task: TaskExecutor | None = None
        if not self.session.model_name:
            self.session.model_name = profile.llm_client.model_name

    def cancel(self) -> Iterable[events.Event]:
        """Handle agent cancellation and tool cancellations."""
        # First, cancel any running task so it stops emitting events.
        if self._current_task is not None:
            yield from self._current_task.cancel()
            self._current_task = None

        log_debug(
            f"Session {self.session.id} interrupted",
            style="yellow",
            debug_type=DebugType.EXECUTION,
        )

    async def run_task(
        self, user_input: UserInputPayload, *, run_subtask: RunSubtask | None = None
    ) -> AsyncGenerator[events.Event]:
        session_ctx = SessionContext(
            session_id=self.session.id,
            get_conversation_history=self.session.get_llm_history,
            append_history=self.session.append_history,
            file_tracker=self.session.file_tracker,
            todo_context=build_todo_context(self.session),
            run_subtask=run_subtask,
        )
        context = TaskExecutionContext(
            session=self.session,
            session_ctx=session_ctx,
            profile=self.profile,
            tool_registry=get_registry(),
            process_reminder=self._process_reminder,
            sub_agent_state=self.session.sub_agent_state,
            compact_llm_client=self.compact_llm_client,
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

        if len(self.session.conversation_history) == 0:
            return

        yield events.ReplayHistoryEvent(
            events=list(self.session.get_history_item()),
            updated_at=self.session.updated_at,
            session_id=self.session.id,
        )

    async def _process_reminder(self, reminder: Reminder) -> AsyncGenerator[events.DeveloperMessageEvent]:
        """Process a single reminder and yield events if it produces output."""
        item = await reminder(self.session)
        if item is not None:
            self.session.append_history([item])
            yield events.DeveloperMessageEvent(session_id=self.session.id, item=item)

    def set_model_profile(self, profile: AgentProfile) -> None:
        """Apply a fully constructed profile to the agent."""

        self.profile = profile
        self.session.model_name = profile.llm_client.model_name

    def get_llm_client(self) -> LLMClientABC:
        return self.profile.llm_client

    def get_partial_metadata(self) -> model.TaskMetadata | None:
        """Get partial metadata from the currently running task.

        Returns None if no task is running or no usage data has been accumulated.
        """
        if self._current_task is None:
            return None
        return self._current_task.get_partial_metadata()
