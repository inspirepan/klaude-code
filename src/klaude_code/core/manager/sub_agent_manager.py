"""Manager for running nested sub-agent tasks.

The :class:`SubAgentManager` encapsulates the logic for creating child
sessions, selecting appropriate LLM clients for sub-agents, and streaming
their events back to the shared event queue.
"""

from __future__ import annotations

import asyncio
import json

from klaude_code.core.agent import Agent, AgentProfile, ModelProfileProvider
from klaude_code.core.manager.llm_clients import LLMClients
from klaude_code.core.tool import ReportBackTool
from klaude_code.protocol import events, model
from klaude_code.protocol.sub_agent import SubAgentResult
from klaude_code.session.session import Session
from klaude_code.trace import DebugType, log_debug


class SubAgentManager:
    """Run sub-agent tasks and forward their events to the UI."""

    def __init__(
        self,
        event_queue: asyncio.Queue[events.Event],
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider,
    ) -> None:
        self._event_queue: asyncio.Queue[events.Event] = event_queue
        self._llm_clients: LLMClients = llm_clients
        self._model_profile_provider: ModelProfileProvider = model_profile_provider

    async def emit_event(self, event: events.Event) -> None:
        """Emit an event to the shared event queue."""

        await self._event_queue.put(event)

    async def run_sub_agent(self, parent_agent: Agent, state: model.SubAgentState) -> SubAgentResult:
        """Run a nested sub-agent task and return its result."""

        parent_session = parent_agent.session
        resume_session_id = state.resume

        def _append_agent_id(task_result: str, session_id: str) -> str:
            trimmed = (task_result or "").rstrip()
            footer = f"agentId: {session_id} (for resuming to continue this agent's work if needed)"
            if trimmed.strip():
                return f"{trimmed}\n\n{footer}"
            return footer

        if resume_session_id:
            try:
                child_session = Session.load(resume_session_id)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return SubAgentResult(
                    task_result=f"Failed to resume sub-agent session '{resume_session_id}': {exc}",
                    session_id="",
                    error=True,
                )

            if child_session.sub_agent_state is None:
                return SubAgentResult(
                    task_result=(f"Invalid resume id '{resume_session_id}': target session is not a sub-agent session"),
                    session_id="",
                    error=True,
                )
            if child_session.sub_agent_state.sub_agent_type != state.sub_agent_type:
                return SubAgentResult(
                    task_result=(
                        "Invalid resume id: sub-agent type mismatch. "
                        f"Expected '{state.sub_agent_type}', got '{child_session.sub_agent_state.sub_agent_type}'."
                    ),
                    session_id="",
                    error=True,
                )

            # Update persisted sub-agent state to reflect the current invocation.
            child_session.sub_agent_state.sub_agent_desc = state.sub_agent_desc
            child_session.sub_agent_state.sub_agent_prompt = state.sub_agent_prompt
            child_session.sub_agent_state.resume = resume_session_id
            child_session.sub_agent_state.output_schema = state.output_schema
            child_session.sub_agent_state.generation = state.generation
        else:
            # Create a new child session under the same workdir
            child_session = Session(work_dir=parent_session.work_dir)
            child_session.sub_agent_state = state

        child_profile = self._model_profile_provider.build_profile(
            self._llm_clients.get_client(state.sub_agent_type),
            state.sub_agent_type,
        )

        # Inject report_back tool if output_schema is provided
        if state.output_schema:
            report_back_tool_class = ReportBackTool.for_schema(state.output_schema)
            report_back_prompt = """\

# Structured Output
You have a `report_back` tool available. When you complete the task,\
you MUST call `report_back` with the structured result matching the required schema.\
Only the content passed to `report_back` will be returned to user.\
"""
            base_prompt = child_profile.system_prompt or ""
            child_profile = AgentProfile(
                llm_client=child_profile.llm_client,
                system_prompt=base_prompt + report_back_prompt,
                tools=[*child_profile.tools, report_back_tool_class.schema()],
                reminders=child_profile.reminders,
            )

        child_agent = Agent(session=child_session, profile=child_profile)

        log_debug(
            f"Running sub-agent {state.sub_agent_type} in session {child_session.id}",
            style="cyan",
            debug_type=DebugType.EXECUTION,
        )

        try:
            # Not emit the subtask's user input since task tool call is already rendered
            result: str = ""
            task_metadata: model.TaskMetadata | None = None
            sub_agent_input = model.UserInputPayload(text=state.sub_agent_prompt, images=None)
            child_session.append_history(
                [
                    model.UserMessage(
                        parts=model.parts_from_text_and_images(sub_agent_input.text, sub_agent_input.images)
                    )
                ]
            )
            async for event in child_agent.run_task(sub_agent_input):
                # Capture TaskFinishEvent content for return
                if isinstance(event, events.TaskFinishEvent):
                    result = event.task_result
                    event = events.TaskFinishEvent(
                        session_id=event.session_id,
                        task_result=_append_agent_id(event.task_result, child_session.id),
                        has_structured_output=event.has_structured_output,
                    )
                # Capture TaskMetadataEvent for metadata propagation
                elif isinstance(event, events.TaskMetadataEvent):
                    task_metadata = event.metadata.main_agent
                await self.emit_event(event)

            # Ensure the sub-agent session is persisted before returning its id for resume.
            await child_session.wait_for_flush()
            return SubAgentResult(
                task_result=result,
                session_id=child_session.id,
                task_metadata=task_metadata,
            )
        except asyncio.CancelledError:
            # Propagate cancellation so tooling can treat it as user interrupt
            log_debug(
                f"Sub-agent task for {state.sub_agent_type} was cancelled",
                style="yellow",
                debug_type=DebugType.EXECUTION,
            )
            raise
        except Exception as exc:  # pragma: no cover - defensive logging
            log_debug(
                f"Sub-agent task failed: [{exc.__class__.__name__}] {exc!s}",
                style="red",
                debug_type=DebugType.EXECUTION,
            )
            return SubAgentResult(
                task_result=f"Sub-agent task failed: [{exc.__class__.__name__}] {exc!s}",
                session_id="",
                error=True,
            )
