from __future__ import annotations

from collections.abc import AsyncGenerator, Iterable
from dataclasses import dataclass
from typing import Protocol

from klaude_code.core.prompt import load_system_prompt
from klaude_code.core.reminders import Reminder, load_agent_reminders
from klaude_code.core.task import SessionContext, TaskExecutionContext, TaskExecutor
from klaude_code.core.tool import build_todo_context, get_registry, load_agent_tools
from klaude_code.llm import LLMClientABC
from klaude_code.protocol import events, llm_param, model, tools
from klaude_code.protocol.model import UserInputPayload
from klaude_code.session import Session
from klaude_code.trace import DebugType, log_debug


@dataclass(frozen=True)
class AgentProfile:
    """Encapsulates the active LLM client plus prompts/tools/reminders."""

    llm_client: LLMClientABC
    system_prompt: str | None
    tools: list[llm_param.ToolSchema]
    reminders: list[Reminder]


class ModelProfileProvider(Protocol):
    """Strategy interface for constructing agent profiles."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: tools.SubAgentType | None = None,
    ) -> AgentProfile: ...


class DefaultModelProfileProvider(ModelProfileProvider):
    """Default provider backed by global prompts/tool/reminder registries."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: tools.SubAgentType | None = None,
    ) -> AgentProfile:
        model_name = llm_client.model_name
        return AgentProfile(
            llm_client=llm_client,
            system_prompt=load_system_prompt(model_name, llm_client.protocol, sub_agent_type),
            tools=load_agent_tools(model_name, sub_agent_type),
            reminders=load_agent_reminders(model_name, sub_agent_type),
        )


class VanillaModelProfileProvider(ModelProfileProvider):
    """Provider that strips prompts, reminders, and tools for vanilla mode."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: tools.SubAgentType | None = None,
    ) -> AgentProfile:
        model_name = llm_client.model_name
        return AgentProfile(
            llm_client=llm_client,
            system_prompt=None,
            tools=load_agent_tools(model_name, vanilla=True),
            reminders=load_agent_reminders(model_name, vanilla=True),
        )


class Agent:
    def __init__(
        self,
        session: Session,
        profile: AgentProfile,
    ):
        self.session: Session = session
        self.profile: AgentProfile = profile
        self._current_task: TaskExecutor | None = None
        if not self.session.model_name:
            self.session.model_name = profile.llm_client.model_name

    def cancel(self) -> Iterable[events.Event]:
        """Handle agent cancellation and persist an interrupt marker and tool cancellations.

        - Appends an `InterruptItem` into the session history so interruptions are reflected
          in persisted conversation logs.
        - For any tool calls that are pending or in-progress in the current task, delegate to
          the active TaskExecutor to append synthetic ToolResultItem entries with error status
          to indicate cancellation.
        """
        # First, cancel any running task so it stops emitting events.
        if self._current_task is not None:
            yield from self._current_task.cancel()
            self._current_task = None

        # Record an interrupt marker in the session history
        self.session.append_history([model.InterruptItem()])
        log_debug(
            f"Session {self.session.id} interrupted",
            style="yellow",
            debug_type=DebugType.EXECUTION,
        )

    async def run_task(self, user_input: UserInputPayload) -> AsyncGenerator[events.Event]:
        session_ctx = SessionContext(
            session_id=self.session.id,
            get_conversation_history=lambda: self.session.conversation_history,
            append_history=self.session.append_history,
            file_tracker=self.session.file_tracker,
            todo_context=build_todo_context(self.session),
        )
        context = TaskExecutionContext(
            session_ctx=session_ctx,
            profile=self.profile,
            tool_registry=get_registry(),
            process_reminder=self._process_reminder,
            sub_agent_state=self.session.sub_agent_state,
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
