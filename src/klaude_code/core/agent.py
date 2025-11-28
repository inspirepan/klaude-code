from __future__ import annotations

from collections.abc import AsyncGenerator, Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

from klaude_code.core.prompt import get_system_prompt as load_system_prompt
from klaude_code.core.reminders import (
    Reminder,
    get_main_agent_reminders,
    get_sub_agent_reminders,
    get_vanilla_reminders,
)
from klaude_code.core.sub_agent import get_sub_agent_profile
from klaude_code.core.task import TaskExecutionContext, TaskExecutor
from klaude_code.core.tool.tool_context import TodoContext
from klaude_code.core.tool.tool_registry import (
    get_main_agent_tools,
    get_registry,
    get_sub_agent_tools,
    get_vanilla_tools,
)
from klaude_code.llm.client import LLMClientABC
from klaude_code.protocol import events, llm_parameter, model, tools
from klaude_code.session import Session
from klaude_code.trace import DebugType, log_debug


@dataclass
class AgentLLMClients:
    main: LLMClientABC
    fast: LLMClientABC | None = None  # Not used for now
    sub_clients: dict[tools.SubAgentType, LLMClientABC | None] = field(
        default_factory=lambda: cast(dict[tools.SubAgentType, LLMClientABC | None], {})
    )

    def get_sub_agent_client(self, sub_agent_type: tools.SubAgentType) -> LLMClientABC:
        return self.sub_clients.get(sub_agent_type) or self.main

    def set_sub_agent_client(self, sub_agent_type: tools.SubAgentType, client: LLMClientABC) -> None:
        self.sub_clients[sub_agent_type] = client


@dataclass(frozen=True)
class AgentRole:
    """Defines the role context when configuring an agent."""

    name: Literal["main", "sub"]
    sub_agent_type: tools.SubAgentType | None = None

    @classmethod
    def main(cls) -> "AgentRole":
        return cls(name="main")

    @classmethod
    def sub(cls, sub_agent_type: tools.SubAgentType) -> "AgentRole":
        return cls(name="sub", sub_agent_type=sub_agent_type)

    def require_sub_agent_type(self) -> tools.SubAgentType:
        if self.sub_agent_type is None:
            raise ValueError("Sub-agent role requires sub_agent_type")
        return self.sub_agent_type


@dataclass(frozen=True)
class AgentProfile:
    """Encapsulates the active LLM client plus prompt/tools/reminders."""

    llm_client: LLMClientABC
    role: AgentRole
    system_prompt: str | None
    tools: list[llm_parameter.ToolSchema]
    reminders: list[Reminder]


class ModelProfileProvider(Protocol):
    """Strategy interface for constructing agent profiles."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        agent_role: AgentRole,
    ) -> AgentProfile: ...


class DefaultModelProfileProvider(ModelProfileProvider):
    """Default provider backed by global prompt/tool/reminder registries."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        agent_role: AgentRole,
    ) -> AgentProfile:
        model_name = llm_client.model_name

        if agent_role.name == "main":
            prompt_key = "main"
        else:
            prompt_key = get_sub_agent_profile(agent_role.require_sub_agent_type()).name
        system_prompt = load_system_prompt(model_name, prompt_key)

        if agent_role.name == "main":
            tools = get_main_agent_tools(model_name)
            reminders = get_main_agent_reminders(model_name)
        else:
            sub_agent_type = agent_role.require_sub_agent_type()
            tools = get_sub_agent_tools(model_name, sub_agent_type)
            reminders = get_sub_agent_reminders(model_name)

        return AgentProfile(
            llm_client=llm_client,
            role=agent_role,
            system_prompt=system_prompt,
            tools=tools,
            reminders=reminders,
        )


class VanillaModelProfileProvider(ModelProfileProvider):
    """Provider that strips prompts, reminders, and tools for vanilla mode."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        agent_role: AgentRole,
    ) -> AgentProfile:
        return AgentProfile(
            llm_client=llm_client,
            role=agent_role,
            system_prompt=None,
            tools=get_vanilla_tools(),
            reminders=get_vanilla_reminders(),
        )


class Agent:
    def __init__(
        self,
        llm_clients: AgentLLMClients,
        session: Session,
        initial_profile: AgentProfile,
        *,
        model_profile_provider: ModelProfileProvider | None = None,
    ):
        self.session: Session = session
        self.llm_clients = llm_clients
        self.model_profile_provider: ModelProfileProvider = model_profile_provider or DefaultModelProfileProvider()
        self.profile: AgentProfile | None = None
        # Active task executor, if any
        self._current_task: TaskExecutor | None = None
        # Ensure runtime configuration matches the active model on initialization
        self.set_model_profile(initial_profile)

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
        log_debug(f"Session {self.session.id} interrupted", style="yellow", debug_type=DebugType.EXECUTION)

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
            events=list(self.session.get_history_item()), updated_at=self.session.updated_at, session_id=self.session.id
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
        # Keep shared client registry in sync for main-agent switches
        if profile.role.name == "main":
            self.llm_clients.main = profile.llm_client
        self.session.model_name = profile.llm_client.model_name

    def build_model_profile(
        self,
        llm_client: LLMClientABC,
        agent_role: AgentRole | None = None,
    ) -> AgentProfile:
        if agent_role is None:
            agent_role = AgentRole.main()
        return self.model_profile_provider.build_profile(llm_client, agent_role)

    def get_llm_client(self) -> LLMClientABC:
        return self._require_profile().llm_client

    def _require_profile(self) -> AgentProfile:
        if self.profile is None:
            raise RuntimeError("Agent profile is not initialized")
        return self.profile
