"""Sub-agent execution and event forwarding."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from string import Template

from klaude_code.core.agent.agent import Agent
from klaude_code.core.agent.runtime_llm import LLMClients
from klaude_code.core.agent_profile import ModelProfileProvider
from klaude_code.core.prompts.system_prompt import load_prompt_by_path
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, message, model
from klaude_code.protocol.sub_agent import SubAgentResult, get_sub_agent_profile
from klaude_code.session.session import Session


class SubAgentExecutor:
    """Run sub-agent tasks and forward their events to the UI."""

    def __init__(
        self,
        emit_event: Callable[[events.Event], Awaitable[None]],
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider,
    ) -> None:
        self._emit_event = emit_event
        self._llm_clients = llm_clients
        self._model_profile_provider = model_profile_provider

    async def emit_event(self, event: events.Event) -> None:
        await self._emit_event(event)

    async def run_sub_agent(
        self,
        parent_agent: Agent,
        state: model.SubAgentState,
        *,
        llm_clients: LLMClients | None = None,
        record_session_id: Callable[[str], None] | None = None,
        register_metadata_getter: Callable[[Callable[[], model.TaskMetadata | None]], None] | None = None,
        register_progress_getter: Callable[[Callable[[], str | None]], None] | None = None,
    ) -> SubAgentResult:
        parent_session = parent_agent.session

        if state.fork_context:
            # Exclude the trailing AssistantMessage that contains the in-flight Agent tool call
            # and any ToolResultMessages from concurrent tools that already completed.
            # We cannot simply use len(history) - 1 because concurrent tool results may have
            # been appended after the AssistantMessage, shifting the index.
            history = parent_session.conversation_history
            fork_index = len(history)
            for i in range(len(history) - 1, -1, -1):
                if isinstance(history[i], message.AssistantMessage):
                    fork_index = i
                    break
            child_session = parent_session.fork(until_index=fork_index)
        else:
            child_session = Session(work_dir=parent_session.work_dir)
        child_session.sub_agent_state = state

        # Record the sub-agent session ID in the parent session's history so that
        # history replay can discover and inline the sub-agent's events even before
        # the Agent tool call completes.
        parent_session.append_history(
            [
                message.SpawnSubAgentEntry(
                    session_id=child_session.id,
                    sub_agent_type=state.sub_agent_type,
                    sub_agent_desc=state.sub_agent_desc,
                    fork_context=state.fork_context,
                )
            ]
        )

        if record_session_id is not None:
            record_session_id(child_session.id)

        if state.fork_context:
            # Fork mode: reuse the parent agent's profile (same system prompt and tools).
            child_profile = parent_agent.profile
        else:
            clients = llm_clients or self._llm_clients
            child_profile = self._model_profile_provider.build_profile(
                clients.get_client(state.sub_agent_type),
                state.sub_agent_type,
                output_schema=state.output_schema,
                work_dir=parent_session.work_dir,
            )

        child_agent = Agent(
            session=child_session,
            profile=child_profile,
            request_user_interaction=parent_agent.request_user_interaction,
        )

        log_debug(
            f"Running sub-agent {state.sub_agent_type} in session {child_session.id}",
            debug_type=DebugType.EXECUTION,
        )

        def _get_partial_metadata() -> model.TaskMetadata | None:
            metadata = child_agent.get_partial_metadata()
            if metadata is not None:
                metadata.sub_agent_name = state.sub_agent_type
                metadata.description = state.sub_agent_desc or None
            return metadata

        if register_metadata_getter is not None:
            register_metadata_getter(_get_partial_metadata)

        _ARGS_MAX_LEN = 500
        tool_call_log: dict[str, tuple[str, str]] = {}
        completed_calls: set[str] = set()

        def _get_progress() -> str | None:
            if not tool_call_log:
                return None
            lines: list[str] = []
            for call_id, (tool_name, arguments) in tool_call_log.items():
                status = "completed" if call_id in completed_calls else "interrupted"
                args_display = arguments if len(arguments) <= _ARGS_MAX_LEN else arguments[:_ARGS_MAX_LEN] + "..."
                lines.append(f"- {tool_name}({args_display}) [{status}]")
            return "\n".join(lines)

        if register_progress_getter is not None:
            register_progress_getter(_get_progress)

        try:
            result: str = ""
            task_metadata: model.TaskMetadata | None = None
            sub_agent_input = message.UserInputPayload(text=state.sub_agent_prompt, images=None)
            history_items: list[message.HistoryEvent] = []
            if state.fork_context:
                profile = get_sub_agent_profile(state.sub_agent_type)
                if profile.prompt_file:
                    role_prompt = Template(load_prompt_by_path(profile.prompt_file)).safe_substitute(
                        workingDirectory=parent_session.work_dir,
                        workspaceRoot=parent_session.work_dir,
                    )
                    reminder_text = (
                        "You are no longer the main coding agent. "
                        "You are now acting as a specialized sub-agent. "
                        "The conversation history above was forked from the parent session "
                        "-- use it as background context only. "
                        "Do NOT use the Agent tool to spawn sub-agents.\n\n"
                        + role_prompt
                    )
                else:
                    reminder_text = (
                        "You are a newly spawned agent with the full conversation context "
                        "from the parent session. Treat the next user message as your new task, "
                        "and use the conversation history as background context. "
                        "Do NOT use the Agent tool to spawn sub-agents."
                    )
                history_items.append(
                    message.UserMessage(
                        parts=[message.TextPart(text=f"<system-reminder>{reminder_text}</system-reminder>")]
                    )
                )
            history_items.append(
                message.UserMessage(
                    parts=message.parts_from_text_and_images(sub_agent_input.text, sub_agent_input.images)
                )
            )
            child_session.append_history(history_items)
            async for event in child_agent.run_task(sub_agent_input):
                if isinstance(event, events.ToolCallEvent):
                    tool_call_log[event.tool_call_id] = (event.tool_name, event.arguments)
                elif isinstance(event, events.ToolResultEvent):
                    completed_calls.add(event.tool_call_id)

                if isinstance(event, events.TaskFinishEvent):
                    result = event.task_result
                    event = events.TaskFinishEvent(
                        session_id=event.session_id,
                        task_result=result,
                        has_structured_output=event.has_structured_output,
                    )
                elif isinstance(event, events.TaskMetadataEvent):
                    task_metadata = event.metadata.main_agent
                    task_metadata.sub_agent_name = state.sub_agent_type
                    task_metadata.description = state.sub_agent_desc or None
                await self.emit_event(event)

            await child_session.wait_for_flush()
            return SubAgentResult(
                task_result=result,
                session_id=child_session.id,
                task_metadata=task_metadata,
            )
        except asyncio.CancelledError:
            for evt in child_agent.on_interrupt():
                await self.emit_event(evt)

            log_debug(
                f"Sub-agent task for {state.sub_agent_type} was cancelled",
                debug_type=DebugType.EXECUTION,
            )
            raise
        except Exception as exc:  # pragma: no cover - defensive logging
            log_debug(
                f"Sub-agent task failed: [{exc.__class__.__name__}] {exc!s}",
                debug_type=DebugType.EXECUTION,
            )
            return SubAgentResult(
                task_result=f"Sub-agent task failed: [{exc.__class__.__name__}] {exc!s}",
                session_id=child_session.id,
                error=True,
            )
