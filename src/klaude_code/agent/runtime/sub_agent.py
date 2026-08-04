"""Sub-agent spawning: each sub-agent runs as a first-class server session.

The Agent tool used to execute sub-agents inline inside the parent's task,
forwarding child events through the parent's pipeline. Phase 5 routes them
through their own session actor instead: the launcher prepares the child
session, registers its agent, submits a RunAgentOperation to the child
actor, and follows the child's event stream for the result. Child events
reach clients directly on the bus (tagged with the child session id), so
the child is observable and addressable (ps/attach/kill/respond) like any
other session.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from klaude_code.agent.agent import Agent
from klaude_code.agent.system_prompt import build_sub_agent_env_info, load_prompt_by_path
from klaude_code.config import load_config
from klaude_code.control.event_bus import EventBus
from klaude_code.log import DebugType, log_debug
from klaude_code.prompts.sub_agents import FORK_CONTEXT_GENERAL_PROMPT, FORK_CONTEXT_WITH_ROLE_PROMPT
from klaude_code.protocol import events, message, op
from klaude_code.protocol.models import SubAgentState, TaskMetadata, build_file_changes_since, merge_file_changes
from klaude_code.protocol.sub_agent import SubAgentResult, get_sub_agent_profile
from klaude_code.session.session import Session

if TYPE_CHECKING:
    from klaude_code.agent.runtime.agent_ops import AgentOperationHandler

_ARGS_MAX_LEN = 500


class SubAgentLauncher:
    """Spawn sub-agent sessions through the child's own session actor."""

    def __init__(
        self,
        *,
        handler: AgentOperationHandler,
        event_bus: EventBus,
        submit_operation: Callable[[op.Operation], Awaitable[str]],
        wait_for_operation: Callable[[str], Awaitable[str | None]],
    ) -> None:
        self._handler = handler
        self._event_bus = event_bus
        self._submit_operation = submit_operation
        self._wait_for_operation = wait_for_operation

    async def run_sub_agent(
        self,
        parent_agent: Agent,
        state: SubAgentState,
        *,
        record_session_id: Callable[[str], None] | None = None,
        register_metadata_getter: Callable[[Callable[[], TaskMetadata | None]], None] | None = None,
        register_progress_getter: Callable[[Callable[[], str | None]], None] | None = None,
    ) -> SubAgentResult:
        parent_session = parent_agent.session
        child_session = self._prepare_child_session(parent_session, state)
        child_file_change_baseline = child_session.file_change_summary.model_copy(deep=True)

        # Record the sub-agent session ID in the parent session's history so that
        # history replay can discover and inline the sub-agent's events even before
        # the Agent tool call completes.
        parent_session.append_history(
            [
                message.SpawnSubAgentEntry(
                    session_id=child_session.id,
                    sub_agent_type=state.sub_agent_type,
                    sub_agent_desc=state.sub_agent_desc,
                    model=(state.model or "").strip() or None,
                    fork_context=state.fork_context,
                    parent_tool_batch_id=state.parent_tool_batch_id,
                    parent_tool_batch_index=state.parent_tool_batch_index,
                    parent_tool_batch_size=state.parent_tool_batch_size,
                )
            ]
        )
        if record_session_id is not None:
            record_session_id(child_session.id)

        self._append_fork_context_reminder(child_session, parent_session, state)

        child_agent = await self._handler.init_sub_agent_session(child_session)

        log_debug(
            f"Running sub-agent {state.sub_agent_type} in session {child_session.id}",
            debug_type=DebugType.EXECUTION,
        )

        def _get_partial_metadata() -> TaskMetadata | None:
            metadata = child_agent.get_partial_metadata()
            if metadata is not None:
                metadata.sub_agent_name = state.sub_agent_type
                metadata.description = state.sub_agent_desc or None
            return metadata

        if register_metadata_getter is not None:
            register_metadata_getter(_get_partial_metadata)

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

        run_op = op.RunAgentOperation(
            session_id=child_session.id,
            input=message.UserInputPayload(text=state.sub_agent_prompt),
        )

        task_result = ""
        task_metadata: TaskMetadata | None = None
        finished = False
        error_message: str | None = None
        status: str | None = None

        # Subscribe before submitting so no child event is missed.
        subscription = self._event_bus.subscribe(child_session.id)
        envelopes = subscription.__aiter__()
        try:
            await self._submit_operation(run_op)
            async for envelope in envelopes:
                event = envelope.event
                if isinstance(event, events.ToolCallEvent):
                    tool_call_log[event.tool_call_id] = (event.tool_name, event.arguments)
                elif isinstance(event, events.ToolResultEvent):
                    completed_calls.add(event.tool_call_id)
                elif isinstance(event, events.TaskFinishEvent):
                    task_result = event.task_result
                    finished = True
                elif isinstance(event, events.TaskMetadataEvent):
                    task_metadata = event.metadata.main_agent
                    task_metadata.sub_agent_name = state.sub_agent_type
                    task_metadata.description = state.sub_agent_desc or None
                elif isinstance(event, events.ErrorEvent):
                    error_message = event.error_message
                elif isinstance(event, events.OperationRejectedEvent) and event.operation_id == run_op.id:
                    status = "rejected"
                    break
                elif isinstance(event, events.OperationFinishedEvent) and event.operation_id == run_op.id:
                    status = event.status
                    break

            if status is None:
                # The bus dropped this subscriber on overflow; fall back to the
                # operation awaiter and recover the result from history.
                status = await self._wait_for_operation(run_op.id) or "completed"
            if not finished and status == "completed" and error_message is None:
                for item in reversed(child_session.conversation_history):
                    if isinstance(item, message.AssistantMessage):
                        text = message.join_text_parts(item.parts)
                        if text.strip():
                            task_result = text
                            finished = True
                            break

            await child_session.wait_for_flush()
            if status in ("failed", "rejected") or not finished:
                log_debug(
                    f"Sub-agent task for {state.sub_agent_type} ended with status={status}: {error_message}",
                    debug_type=DebugType.EXECUTION,
                )
                return SubAgentResult(
                    task_result=error_message or task_result or f"Sub-agent task {status} before completion",
                    session_id=child_session.id,
                    error=True,
                    task_metadata=task_metadata,
                )
            return SubAgentResult(
                task_result=task_result,
                session_id=child_session.id,
                task_metadata=task_metadata,
            )
        finally:
            # Parent interrupt cascades to the child via the dispatcher, so
            # cancellation needs no handling here beyond cleanup.
            await envelopes.aclose()
            child_changes = build_file_changes_since(child_file_change_baseline, child_session.file_change_summary)
            merge_file_changes(parent_session.file_change_summary, child_changes)

    def _prepare_child_session(self, parent_session: Session, state: SubAgentState) -> Session:
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
        child_session.parent_session_id = parent_session.id
        child_session.agent_type = state.sub_agent_type
        child_session.spawn_kind = "subagent"
        if state.fork_context:
            child_session.vanilla = parent_session.vanilla
        model_config_name = self._resolve_child_model(parent_session, state)
        if model_config_name is not None:
            child_session.model_config_name = model_config_name
        return child_session

    @staticmethod
    def _resolve_child_model(parent_session: Session, state: SubAgentState) -> str | None:
        model_override = state.model.strip() if state.model is not None else None
        config = load_config()
        if model_override:
            candidates = config.iter_model_config_candidates(model_override)
            if not candidates:
                # get_model_config raises the precise reason (unknown model,
                # disabled provider, or missing credentials) and never returns
                # when there are no candidates; the raise below is a safety net.
                config.get_model_config(model_override)
                raise ValueError(f"Unknown model: {model_override}")
            return model_override
        if state.fork_context:
            return parent_session.model_config_name
        preference = config.sub_agent_models.get(state.sub_agent_type)
        if preference is not None:
            if isinstance(preference, str):
                return preference
            try:
                return config.get_first_available_model(preference)
            except ValueError:
                pass
        return parent_session.model_config_name

    @staticmethod
    def _append_fork_context_reminder(child_session: Session, parent_session: Session, state: SubAgentState) -> None:
        """Seed a forked child with its role reminder; RunAgentOperation appends the prompt."""
        if not state.fork_context:
            return
        profile = get_sub_agent_profile(state.sub_agent_type)
        if profile.prompt_file:
            role_prompt = load_prompt_by_path(profile.prompt_file) + build_sub_agent_env_info(parent_session.work_dir)
            context_text = FORK_CONTEXT_WITH_ROLE_PROMPT + role_prompt
        else:
            context_text = FORK_CONTEXT_GENERAL_PROMPT
        child_session.append_history(
            [message.UserMessage(parts=[message.TextPart(text=f"<system-reminder>{context_text}</system-reminder>")])]
        )
