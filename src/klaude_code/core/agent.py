from __future__ import annotations

from collections.abc import AsyncGenerator, Iterable
from dataclasses import dataclass
from typing import Protocol

from klaude_code.core.prompt import get_system_prompt as load_system_prompt
from klaude_code.core.reminders import (
    Reminder,
    get_main_agent_reminders,
    get_sub_agent_reminders,
    get_vanilla_reminders,
)
from klaude_code.core.sub_agent import get_sub_agent_profile
from klaude_code.core.task import TaskExecutionContext, TaskExecutor
from klaude_code.core.tool import (
    TodoContext,
    get_main_agent_tools,
    get_registry,
    get_sub_agent_tools,
    get_vanilla_tools,
)
from klaude_code.llm import LLMClientABC
from klaude_code.protocol import events, llm_parameter, model, tools
from klaude_code.session import Session
from klaude_code.trace import DebugType, log_debug


@dataclass(frozen=True)
class AgentProfile:
    """Encapsulates the active LLM client plus prompt/tools/reminders."""

    llm_client: LLMClientABC
    system_prompt: str | None
    tools: list[llm_parameter.ToolSchema]
    reminders: list[Reminder]


class ModelProfileProvider(Protocol):
    """Strategy interface for constructing agent profiles."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: tools.SubAgentType | None = None,
    ) -> AgentProfile: ...


class DefaultModelProfileProvider(ModelProfileProvider):
    """Default provider backed by global prompt/tool/reminder registries."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: tools.SubAgentType | None = None,
    ) -> AgentProfile:
        model_name = llm_client.model_name

        if sub_agent_type is None:
            prompt_key = "main"
            tool_list = get_main_agent_tools(model_name)
            reminders = get_main_agent_reminders(model_name)
        else:
            prompt_key = get_sub_agent_profile(sub_agent_type).name
            tool_list = get_sub_agent_tools(model_name, sub_agent_type)
            reminders = get_sub_agent_reminders(model_name)

        system_prompt = load_system_prompt(model_name, prompt_key)

        return AgentProfile(
            llm_client=llm_client,
            system_prompt=system_prompt,
            tools=tool_list,
            reminders=reminders,
        )


class VanillaModelProfileProvider(ModelProfileProvider):
    """Provider that strips prompts, reminders, and tools for vanilla mode."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: tools.SubAgentType | None = None,
    ) -> AgentProfile:
        return AgentProfile(
            llm_client=llm_client,
            system_prompt=None,
            tools=get_vanilla_tools(),
            reminders=get_vanilla_reminders(),
        )


class Agent:
    def __init__(
        self,
        session: Session,
        profile: AgentProfile,
        *,
        model_profile_provider: ModelProfileProvider | None = None,
    ):
        self.session: Session = session
        self.model_profile_provider: ModelProfileProvider = model_profile_provider or DefaultModelProfileProvider()
        self.profile: AgentProfile | None = None
        # Active task executor, if any
        self._current_task: TaskExecutor | None = None
        # Ensure runtime configuration matches the active model on initialization
        self.set_model_profile(profile)

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
            for ui_event in self._current_task.cancel():
                yield ui_event
            self._current_task = None

        # Record an interrupt marker in the session history
        self.session.append_history([model.InterruptItem()])
        log_debug(
            f"Session {self.session.id} interrupted",
            style="yellow",
            debug_type=DebugType.EXECUTION,
        )

    async def run_task(self, user_input: str) -> AsyncGenerator[events.Event, None]:
        context = TaskExecutionContext(
            session_id=self.session.id,
            profile=self._require_profile(),
            get_conversation_history=lambda: self.session.conversation_history,
            append_history=self.session.append_history,
            tool_registry=get_registry(),
            file_tracker=self.session.file_tracker,
            todo_context=TodoContext(
                get_todos=lambda: self.session.todos,
                set_todos=lambda todos: setattr(self.session, "todos", todos),
            ),
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

    async def replay_history(self) -> AsyncGenerator[events.Event, None]:
        """Yield UI events reconstructed from saved conversation history."""

        if len(self.session.conversation_history) == 0:
            return

        yield events.ReplayHistoryEvent(
            events=list(self.session.get_history_item()),
            updated_at=self.session.updated_at,
            session_id=self.session.id,
        )

    async def _process_reminder(self, reminder: Reminder) -> AsyncGenerator[events.DeveloperMessageEvent, None]:
        """Process a single reminder and yield events if it produces output."""
        item = await reminder(self.session)
        if item is not None:
            self.session.append_history([item])
            yield events.DeveloperMessageEvent(session_id=self.session.id, item=item)

    def set_model_profile(self, profile: AgentProfile) -> None:
        """Apply a fully constructed profile to the agent."""

        self.profile = profile
        self.session.model_name = profile.llm_client.model_name

    def build_model_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: tools.SubAgentType | None = None,
    ) -> AgentProfile:
        return self.model_profile_provider.build_profile(llm_client, sub_agent_type)

    def get_llm_client(self) -> LLMClientABC:
        return self._require_profile().llm_client

    def _require_profile(self) -> AgentProfile:
        if self.profile is None:
            raise RuntimeError("Agent profile is not initialized")
        return self.profile
