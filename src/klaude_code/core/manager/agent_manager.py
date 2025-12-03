"""Agent and session manager.

This module contains :class:`AgentManager`, a helper responsible for
creating and tracking agents per session, applying model changes, and
clearing conversations. It is used by the executor context to keep
agent-related responsibilities separate from operation dispatch.
"""

from __future__ import annotations

import asyncio

from klaude_code.config import load_config
from klaude_code.core.agent import Agent, DefaultModelProfileProvider, ModelProfileProvider
from klaude_code.core.manager.llm_clients import LLMClients
from klaude_code.llm.registry import create_llm_client
from klaude_code.protocol import commands, events, model
from klaude_code.session.session import Session
from klaude_code.trace import DebugType, log_debug


class AgentManager:
    """Manager component that tracks agents and their sessions."""

    def __init__(
        self,
        event_queue: asyncio.Queue[events.Event],
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider | None = None,
    ) -> None:
        self._event_queue: asyncio.Queue[events.Event] = event_queue
        self._llm_clients: LLMClients = llm_clients
        self._model_profile_provider: ModelProfileProvider = model_profile_provider or DefaultModelProfileProvider()
        self._active_agents: dict[str, Agent] = {}

    async def emit_event(self, event: events.Event) -> None:
        """Emit an event to the shared event queue."""

        await self._event_queue.put(event)

    async def ensure_agent(self, session_id: str, *, is_new_session: bool = False) -> Agent:
        """Return an existing agent for the session or create a new one."""
        agent = self._active_agents.get(session_id)
        if agent is not None:
            return agent

        session = Session.load(session_id, skip_if_missing=is_new_session)
        profile = self._model_profile_provider.build_profile(self._llm_clients)
        agent = Agent(session=session, profile=profile, model_name=self._llm_clients.main_model_name)

        async for evt in agent.replay_history():
            await self.emit_event(evt)

        await self.emit_event(
            events.WelcomeEvent(
                work_dir=str(session.work_dir),
                llm_config=self._llm_clients.get_llm_config(),
            )
        )

        self._active_agents[session_id] = agent
        log_debug(
            f"Initialized agent for session: {session_id}",
            style="cyan",
            debug_type=DebugType.EXECUTION,
        )
        return agent

    async def apply_model_change(self, agent: Agent, model_name: str) -> None:
        """Change the model used by an agent and notify the UI."""

        config = load_config()
        if config is None:
            raise ValueError("Configuration must be initialized before changing model")

        llm_config = config.get_model_config(model_name)
        llm_client = create_llm_client(llm_config)
        agent.set_model_profile(self._model_profile_provider.build_profile_eager(llm_client), model_name=model_name)

        developer_item = model.DeveloperMessageItem(
            content=f"switched to model: {model_name}",
            command_output=model.CommandOutput(command_name=commands.CommandName.MODEL),
        )
        agent.session.append_history([developer_item])

        await self.emit_event(events.DeveloperMessageEvent(session_id=agent.session.id, item=developer_item))
        await self.emit_event(events.WelcomeEvent(llm_config=llm_config, work_dir=str(agent.session.work_dir)))

    async def apply_clear(self, agent: Agent) -> None:
        """Start a new conversation for an agent and notify the UI."""

        old_session_id = agent.session.id

        # Create a new session instance to replace the current one
        new_session = Session(work_dir=agent.session.work_dir)
        new_session.model_name = agent.session.model_name

        # Replace the agent's session with the new one
        agent.session = new_session
        agent.session.save()

        # Update the active_agents mapping
        self._active_agents.pop(old_session_id, None)
        self._active_agents[new_session.id] = agent

        developer_item = model.DeveloperMessageItem(
            content="started new conversation",
            command_output=model.CommandOutput(command_name=commands.CommandName.CLEAR),
        )

        await self.emit_event(events.DeveloperMessageEvent(session_id=agent.session.id, item=developer_item))

    def get_active_agent(self, session_id: str) -> Agent | None:
        """Return the active agent for a session id if present."""

        return self._active_agents.get(session_id)

    def active_session_ids(self) -> list[str]:
        """Return a snapshot list of session ids that currently have agents."""

        return list(self._active_agents.keys())

    def all_active_agents(self) -> dict[str, Agent]:
        """Return a snapshot of all active agents keyed by session id."""

        return dict(self._active_agents)
