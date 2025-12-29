"""
Executor module providing the core event loop and task management.

This module implements the submission_loop equivalent for klaude,
handling operations submitted from the CLI and coordinating with agents.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from klaude_code.config import load_config
from klaude_code.core.agent import Agent, DefaultModelProfileProvider, ModelProfileProvider
from klaude_code.core.manager import LLMClients, SubAgentManager
from klaude_code.core.tool import current_run_subtask_callback
from klaude_code.llm.registry import create_llm_client
from klaude_code.protocol import commands, events, model, op
from klaude_code.protocol.llm_param import Thinking
from klaude_code.protocol.op_handler import OperationHandler
from klaude_code.protocol.sub_agent import SubAgentResult
from klaude_code.session.export import build_export_html, get_default_export_path
from klaude_code.session.session import Session
from klaude_code.trace import DebugType, log_debug


@dataclass
class ActiveTask:
    """Track an in-flight task and its owning session."""

    task: asyncio.Task[None]
    session_id: str


class TaskManager:
    """Manager that tracks active tasks keyed by submission id."""

    def __init__(self) -> None:
        self._tasks: dict[str, ActiveTask] = {}

    def register(self, submission_id: str, task: asyncio.Task[None], session_id: str) -> None:
        """Register a new active task for a submission id."""

        self._tasks[submission_id] = ActiveTask(task=task, session_id=session_id)

    def get(self, submission_id: str) -> ActiveTask | None:
        """Return the active task for a submission id if present."""

        return self._tasks.get(submission_id)

    def remove(self, submission_id: str) -> None:
        """Remove the active task associated with a submission id if present."""

        self._tasks.pop(submission_id, None)

    def values(self) -> list[ActiveTask]:
        """Return a snapshot list of all active tasks."""

        return list(self._tasks.values())

    def cancel_tasks_for_sessions(self, session_ids: set[str] | None = None) -> list[tuple[str, asyncio.Task[None]]]:
        """Collect tasks that should be cancelled for given sessions."""

        tasks_to_cancel: list[tuple[str, asyncio.Task[None]]] = []
        for task_id, active in list(self._tasks.items()):
            task = active.task
            if task.done():
                continue
            if session_ids is None or active.session_id in session_ids:
                tasks_to_cancel.append((task_id, task))
        return tasks_to_cancel

    def clear(self) -> None:
        """Remove all tracked tasks from the manager."""

        self._tasks.clear()


class ExecutorContext:
    """
    Context object providing shared state and operations for the executor.

    This context is passed to operations when they execute, allowing them
    to access shared resources like the event queue and active sessions.

    Implements the OperationHandler protocol via structural subtyping.
    """

    def __init__(
        self,
        event_queue: asyncio.Queue[events.Event],
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider | None = None,
        on_model_change: Callable[[str], None] | None = None,
    ):
        self.event_queue: asyncio.Queue[events.Event] = event_queue
        self.llm_clients: LLMClients = llm_clients

        resolved_profile_provider = model_profile_provider or DefaultModelProfileProvider()
        self.model_profile_provider: ModelProfileProvider = resolved_profile_provider

        self.task_manager = TaskManager()
        self.sub_agent_manager = SubAgentManager(event_queue, llm_clients, resolved_profile_provider)
        self._on_model_change = on_model_change
        self._agent: Agent | None = None

    async def emit_event(self, event: events.Event) -> None:
        """Emit an event to the UI display system."""
        await self.event_queue.put(event)

    def current_session_id(self) -> str | None:
        """Return the primary active session id, if any.

        This is a convenience wrapper used by the CLI, which conceptually
        operates on a single interactive session per process.
        """

        agent = self._agent
        if agent is None:
            return None
        return agent.session.id

    @property
    def current_agent(self) -> Agent | None:
        """Return the currently active agent, if any."""

        return self._agent

    async def _ensure_agent(self, session_id: str | None = None) -> Agent:
        """Return the active agent, creating or loading a session as needed.

        If ``session_id`` is ``None``, a new session is created with an
        auto-generated ID. If provided, the executor attempts to resume the
        session from disk or creates a new one if not found.
        """

        # Fast-path: reuse current agent when the session id already matches.
        if session_id is not None and self._agent is not None and self._agent.session.id == session_id:
            return self._agent

        session = Session.create() if session_id is None else Session.load(session_id)

        if (
            session.model_thinking is not None
            and session.model_name
            and session.model_name == self.llm_clients.main.model_name
        ):
            self.llm_clients.main.get_llm_config().thinking = session.model_thinking

        profile = self.model_profile_provider.build_profile(self.llm_clients.main)
        agent = Agent(session=session, profile=profile)

        async for evt in agent.replay_history():
            await self.emit_event(evt)

        await self.emit_event(
            events.WelcomeEvent(
                work_dir=str(session.work_dir),
                llm_config=self.llm_clients.main.get_llm_config(),
            )
        )

        self._agent = agent
        log_debug(
            f"Initialized agent for session: {session.id}",
            style="cyan",
            debug_type=DebugType.EXECUTION,
        )
        return agent

    async def handle_init_agent(self, operation: op.InitAgentOperation) -> None:
        """Initialize an agent for a session and replay history to UI."""
        await self._ensure_agent(operation.session_id)

    async def handle_user_input(self, operation: op.UserInputOperation) -> None:
        """Handle a user input operation.

        Core should not parse slash commands. The UI/CLI layer is responsible for
        turning raw user input into one or more operations.
        """

        if operation.session_id is None:
            raise ValueError("session_id cannot be None")

        session_id = operation.session_id
        agent = await self._ensure_agent(session_id)
        user_input = operation.input

        await self.emit_event(
            events.UserMessageEvent(content=user_input.text, session_id=session_id, images=user_input.images)
        )
        agent.session.append_history([model.UserMessageItem(content=user_input.text, images=user_input.images)])

        await self.handle_run_agent(
            op.RunAgentOperation(
                id=operation.id,
                session_id=session_id,
                input=user_input,
            )
        )

    async def handle_run_agent(self, operation: op.RunAgentOperation) -> None:
        agent = await self._ensure_agent(operation.session_id)
        existing_active = self.task_manager.get(operation.id)
        if existing_active is not None and not existing_active.task.done():
            raise RuntimeError(f"Active task already registered for operation {operation.id}")
        task: asyncio.Task[None] = asyncio.create_task(
            self._run_agent_task(agent, operation.input, operation.id, operation.session_id)
        )
        self.task_manager.register(operation.id, task, operation.session_id)

    async def handle_change_model(self, operation: op.ChangeModelOperation) -> None:
        agent = await self._ensure_agent(operation.session_id)
        config = load_config()

        llm_config = config.get_model_config(operation.model_name)
        llm_client = create_llm_client(llm_config)
        agent.set_model_profile(self.model_profile_provider.build_profile(llm_client))

        agent.session.model_config_name = operation.model_name
        agent.session.model_thinking = llm_config.thinking

        if operation.save_as_default:
            config.main_model = operation.model_name
            await config.save()

        if operation.emit_switch_message:
            default_note = " (saved as default)" if operation.save_as_default else ""
            developer_item = model.DeveloperMessageItem(
                content=f"Switched to: {llm_config.model}{default_note}",
                command_output=model.CommandOutput(command_name=commands.CommandName.MODEL),
            )
            agent.session.append_history([developer_item])
            await self.emit_event(events.DeveloperMessageEvent(session_id=agent.session.id, item=developer_item))

        if self._on_model_change is not None:
            self._on_model_change(llm_client.model_name)

        if operation.emit_welcome_event:
            await self.emit_event(events.WelcomeEvent(llm_config=llm_config, work_dir=str(agent.session.work_dir)))

    async def handle_change_thinking(self, operation: op.ChangeThinkingOperation) -> None:
        """Handle a change thinking operation.

        Interactive thinking selection must happen in the UI/CLI layer. Core only
        applies a concrete thinking configuration.
        """
        agent = await self._ensure_agent(operation.session_id)

        config = agent.profile.llm_client.get_llm_config()

        def _format_thinking_for_display(thinking: Thinking | None) -> str:
            if thinking is None:
                return "not configured"
            if thinking.reasoning_effort:
                return f"reasoning_effort={thinking.reasoning_effort}"
            if thinking.type == "disabled":
                return "off"
            if thinking.type == "enabled":
                if thinking.budget_tokens is None:
                    return "enabled"
                return f"enabled (budget_tokens={thinking.budget_tokens})"
            return "not set"

        if operation.thinking is None:
            raise ValueError("thinking must be provided; interactive selection belongs to UI")

        current = _format_thinking_for_display(config.thinking)
        config.thinking = operation.thinking
        agent.session.model_thinking = operation.thinking
        new_status = _format_thinking_for_display(config.thinking)

        if operation.emit_switch_message:
            developer_item = model.DeveloperMessageItem(
                content=f"Thinking changed: {current} -> {new_status}",
                command_output=model.CommandOutput(command_name=commands.CommandName.THINKING),
            )
            agent.session.append_history([developer_item])
            await self.emit_event(events.DeveloperMessageEvent(session_id=agent.session.id, item=developer_item))

        if operation.emit_welcome_event:
            await self.emit_event(events.WelcomeEvent(work_dir=str(agent.session.work_dir), llm_config=config))

    async def handle_clear_session(self, operation: op.ClearSessionOperation) -> None:
        agent = await self._ensure_agent(operation.session_id)
        new_session = Session.create(work_dir=agent.session.work_dir)
        new_session.model_name = agent.session.model_name
        new_session.model_config_name = agent.session.model_config_name
        new_session.model_thinking = agent.session.model_thinking
        agent.session = new_session

        developer_item = model.DeveloperMessageItem(
            content="started new conversation",
            command_output=model.CommandOutput(command_name=commands.CommandName.CLEAR),
        )
        await self.emit_event(events.DeveloperMessageEvent(session_id=agent.session.id, item=developer_item))

    async def handle_resume_session(self, operation: op.ResumeSessionOperation) -> None:
        target_session = Session.load(operation.target_session_id)
        if (
            target_session.model_thinking is not None
            and target_session.model_name
            and target_session.model_name == self.llm_clients.main.model_name
        ):
            self.llm_clients.main.get_llm_config().thinking = target_session.model_thinking

        profile = self.model_profile_provider.build_profile(self.llm_clients.main)
        from klaude_code.core.agent import Agent

        agent = Agent(session=target_session, profile=profile)

        async for evt in agent.replay_history():
            await self.emit_event(evt)

        await self.emit_event(
            events.WelcomeEvent(
                work_dir=str(target_session.work_dir),
                llm_config=self.llm_clients.main.get_llm_config(),
            )
        )

        self._agent = agent
        log_debug(
            f"Resumed session: {target_session.id}",
            style="cyan",
            debug_type=DebugType.EXECUTION,
        )

    async def handle_export_session(self, operation: op.ExportSessionOperation) -> None:
        agent = await self._ensure_agent(operation.session_id)
        try:
            output_path = self._resolve_export_output_path(operation.output_path, agent.session)
            html_doc = self._build_export_html(agent)
            await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(output_path.write_text, html_doc, "utf-8")
            await asyncio.to_thread(self._open_file, output_path)
            developer_item = model.DeveloperMessageItem(
                content=f"Session exported and opened: {output_path}",
                command_output=model.CommandOutput(command_name=commands.CommandName.EXPORT),
            )
            agent.session.append_history([developer_item])
            await self.emit_event(events.DeveloperMessageEvent(session_id=agent.session.id, item=developer_item))
        except Exception as exc:  # pragma: no cover
            import traceback

            developer_item = model.DeveloperMessageItem(
                content=f"Failed to export session: {exc}\n{traceback.format_exc()}",
                command_output=model.CommandOutput(command_name=commands.CommandName.EXPORT, is_error=True),
            )
            agent.session.append_history([developer_item])
            await self.emit_event(events.DeveloperMessageEvent(session_id=agent.session.id, item=developer_item))

    async def _run_agent_task(
        self,
        agent: Agent,
        user_input: model.UserInputPayload,
        task_id: str,
        session_id: str,
    ) -> None:
        try:
            log_debug(
                f"Starting agent task {task_id} for session {session_id}",
                style="green",
                debug_type=DebugType.EXECUTION,
            )

            async def _runner(state: model.SubAgentState) -> SubAgentResult:
                return await self.sub_agent_manager.run_sub_agent(agent, state)

            token = current_run_subtask_callback.set(_runner)
            try:
                async for event in agent.run_task(user_input):
                    await self.emit_event(event)
            finally:
                current_run_subtask_callback.reset(token)

        except asyncio.CancelledError:
            log_debug(
                f"Agent task {task_id} was cancelled",
                style="yellow",
                debug_type=DebugType.EXECUTION,
            )
            await self.emit_event(events.TaskFinishEvent(session_id=session_id, task_result="task cancelled"))

        except Exception as e:
            import traceback

            log_debug(
                f"Agent task {task_id} failed: {e!s}",
                style="red",
                debug_type=DebugType.EXECUTION,
            )
            log_debug(traceback.format_exc(), style="red", debug_type=DebugType.EXECUTION)
            await self.emit_event(
                events.ErrorEvent(
                    error_message=f"Agent task failed: [{e.__class__.__name__}] {e!s} {traceback.format_exc()}",
                    can_retry=False,
                )
            )
        finally:
            self.task_manager.remove(task_id)
            log_debug(
                f"Cleaned up agent task {task_id}",
                style="cyan",
                debug_type=DebugType.EXECUTION,
            )

    def _resolve_export_output_path(self, raw: str | None, session: Session) -> Path:
        trimmed = (raw or "").strip()
        if trimmed:
            candidate = Path(trimmed).expanduser()
            if not candidate.is_absolute():
                candidate = Path(session.work_dir) / candidate
            if candidate.suffix.lower() != ".html":
                candidate = candidate.with_suffix(".html")
            return candidate
        return get_default_export_path(session)

    def _build_export_html(self, agent: Agent) -> str:
        profile = agent.profile
        system_prompt = (profile.system_prompt if profile else "") or ""
        tool_schemas = profile.tools if profile else []
        model_name = profile.llm_client.model_name if profile else "unknown"
        return build_export_html(agent.session, system_prompt, tool_schemas, model_name)

    def _open_file(self, path: Path) -> None:
        try:
            # Detach stdin to prevent interference with prompt_toolkit's terminal state
            subprocess.run(["open", str(path)], stdin=subprocess.DEVNULL, check=True)
        except FileNotFoundError as exc:  # pragma: no cover
            msg = "`open` command not found; please open the HTML manually."
            raise RuntimeError(msg) from exc
        except subprocess.CalledProcessError as exc:  # pragma: no cover
            msg = f"Failed to open HTML with `open`: {exc}"
            raise RuntimeError(msg) from exc

    async def handle_interrupt(self, operation: op.InterruptOperation) -> None:
        """Handle an interrupt by invoking agent.cancel() and cancelling tasks."""

        # Determine affected sessions
        if operation.target_session_id is not None:
            session_ids: list[str] = [operation.target_session_id]
        else:
            agent = self._agent
            session_ids = [agent.session.id] if agent is not None else []

        # Call cancel() on each affected agent to persist an interrupt marker
        for sid in session_ids:
            agent = self._get_active_agent(sid)
            if agent is not None:
                for evt in agent.cancel():
                    await self.emit_event(evt)

        # emit interrupt event
        await self.emit_event(events.InterruptEvent(session_id=operation.target_session_id or "all"))

        # Find tasks to cancel (filter by target sessions if provided)
        if operation.target_session_id is None:
            session_filter: set[str] | None = None
        else:
            session_filter = {operation.target_session_id}

        tasks_to_cancel = self.task_manager.cancel_tasks_for_sessions(session_filter)

        scope = operation.target_session_id or "all"
        log_debug(
            f"Interrupting {len(tasks_to_cancel)} task(s) for: {scope}",
            style="yellow",
            debug_type=DebugType.EXECUTION,
        )

        # Cancel the tasks
        for task_id, task in tasks_to_cancel:
            task.cancel()
            # Remove from active tasks immediately
            self.task_manager.remove(task_id)

    def get_active_task(self, submission_id: str) -> asyncio.Task[None] | None:
        """Return the asyncio.Task for a submission id if one is registered."""

        active = self.task_manager.get(submission_id)
        if active is None:
            return None
        return active.task

    def has_active_task(self, submission_id: str) -> bool:
        """Return True if a task is registered for the submission id."""

        return self.task_manager.get(submission_id) is not None

    def _get_active_agent(self, session_id: str) -> Agent | None:
        """Return the active agent if its session id matches ``session_id``."""

        agent = self._agent
        if agent is None:
            return None
        if agent.session.id != session_id:
            return None
        return agent


class Executor:
    """
    Core executor that processes operations submitted from the CLI.

    This class implements a message loop similar to Codex-rs's submission_loop,
    processing operations asynchronously and coordinating with agents.
    """

    def __init__(
        self,
        event_queue: asyncio.Queue[events.Event],
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider | None = None,
        on_model_change: Callable[[str], None] | None = None,
    ):
        self.context = ExecutorContext(event_queue, llm_clients, model_profile_provider, on_model_change)
        self.submission_queue: asyncio.Queue[op.Submission] = asyncio.Queue()
        # Track completion events for all submissions (not just those with ActiveTask)
        self._completion_events: dict[str, asyncio.Event] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def submit(self, operation: op.Operation) -> str:
        """
        Submit an operation to the executor for processing.

        Args:
            operation: Operation to submit

        Returns:
            Unique submission ID for tracking
        """

        submission = op.Submission(id=operation.id, operation=operation)
        await self.submission_queue.put(submission)

        # Create completion event for tracking
        self._completion_events[operation.id] = asyncio.Event()

        log_debug(
            f"Submitted operation {operation.type} with ID {operation.id}",
            style="blue",
            debug_type=DebugType.EXECUTION,
        )

        return operation.id

    async def wait_for(self, submission_id: str) -> None:
        """Wait for a specific submission to complete."""
        event = self._completion_events.get(submission_id)
        if event is not None:
            await event.wait()
            self._completion_events.pop(submission_id, None)

    async def submit_and_wait(self, operation: op.Operation) -> None:
        """Submit an operation and wait for it to complete."""
        submission_id = await self.submit(operation)
        await self.wait_for(submission_id)

    async def start(self) -> None:
        """
        Start the executor main loop.

        This method runs continuously, processing submissions from the queue
        until the executor is stopped.
        """
        log_debug("Executor started", style="green", debug_type=DebugType.EXECUTION)

        while True:
            try:
                # Wait for next submission
                submission = await self.submission_queue.get()

                # Check for end operation to gracefully exit
                if isinstance(submission.operation, op.EndOperation):
                    log_debug(
                        "Received EndOperation, stopping executor",
                        style="yellow",
                        debug_type=DebugType.EXECUTION,
                    )
                    break

                await self._handle_submission(submission)

            except asyncio.CancelledError:
                # Executor was cancelled
                log_debug("Executor cancelled", style="yellow", debug_type=DebugType.EXECUTION)
                break

            except Exception as e:
                # Handle unexpected errors
                log_debug(
                    f"Executor error: {e!s}",
                    style="red",
                    debug_type=DebugType.EXECUTION,
                )
                await self.context.emit_event(
                    events.ErrorEvent(error_message=f"Executor error: {e!s}", can_retry=False)
                )

    async def stop(self) -> None:
        """Stop the executor and clean up resources."""
        # Cancel all active tasks and collect them for awaiting
        tasks_to_await: list[asyncio.Task[None]] = []
        for active in self.context.task_manager.values():
            task = active.task
            if not task.done():
                task.cancel()
                tasks_to_await.append(task)

        # Wait for all cancelled tasks to complete
        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)

        # Clear the active task manager
        self.context.task_manager.clear()

        # Send EndOperation to wake up the start() loop
        try:
            end_operation = op.EndOperation()
            submission = op.Submission(id=end_operation.id, operation=end_operation)
            await self.submission_queue.put(submission)
        except Exception as e:
            log_debug(
                f"Failed to send EndOperation: {e!s}",
                style="red",
                debug_type=DebugType.EXECUTION,
            )

        log_debug("Executor stopped", style="yellow", debug_type=DebugType.EXECUTION)

    async def _handle_submission(self, submission: op.Submission) -> None:
        """
        Handle a single submission by executing its operation.

        This method delegates to the operation's execute method, which
        can access shared resources through the executor context.
        """
        try:
            log_debug(
                f"Handling submission {submission.id} of type {submission.operation.type.value}",
                style="cyan",
                debug_type=DebugType.EXECUTION,
            )

            # Execute to spawn the agent task in context
            await submission.operation.execute(handler=self.context)

            task = self.context.get_active_task(submission.id)

            async def _await_agent_and_complete(captured_task: asyncio.Task[None]) -> None:
                try:
                    await captured_task
                finally:
                    event = self._completion_events.get(submission.id)
                    if event is not None:
                        event.set()

            if task is None:
                event = self._completion_events.get(submission.id)
                if event is not None:
                    event.set()
            else:
                # Run in background so the submission loop can continue (e.g., to handle interrupts)
                background_task = asyncio.create_task(_await_agent_and_complete(task))
                self._background_tasks.add(background_task)
                background_task.add_done_callback(self._background_tasks.discard)

        except Exception as e:
            log_debug(
                f"Failed to handle submission {submission.id}: {e!s}",
                style="red",
                debug_type=DebugType.EXECUTION,
            )
            await self.context.emit_event(events.ErrorEvent(error_message=f"Operation failed: {e!s}", can_retry=False))
            # Set completion event even on error to prevent wait_for_completion from hanging
            event = self._completion_events.get(submission.id)
            if event is not None:
                event.set()


# Static type check: ExecutorContext must satisfy OperationHandler protocol.
# If this line causes a type error, ExecutorContext is missing required methods.
_: type[OperationHandler] = ExecutorContext
