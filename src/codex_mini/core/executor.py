"""
Executor module providing the core event loop and task management.

This module implements the submission_loop equivalent for codex-mini,
handling operations submitted from the CLI and coordinating with agents.
"""

import asyncio
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from codex_mini.core.agent import Agent
from codex_mini.core.prompt import get_system_prompt
from codex_mini.core.reminders import (
    empty_todo_reminder,
    file_changed_externally_reminder,
    last_path_memory_reminder,
    memory_reminder,
    todo_not_used_recently_reminder,
)
from codex_mini.core.tool import get_tool_schemas
from codex_mini.llm.client import LLMClientABC
from codex_mini.protocol import events, llm_parameter
from codex_mini.protocol.op import InitAgentOperation, InterruptOperation, OperationType, Submission, UserInputOperation
from codex_mini.protocol.tools import (
    BASH_TOOL_NAME,
    EDIT_TOOL_NAME,
    MULTI_EDIT_TOOL_NAME,
    READ_TOOL_NAME,
    TODO_WRITE_TOOL_NAME,
)
from codex_mini.session.session import Session
from codex_mini.trace import log_debug


class ExecutorContext:
    """
    Context object providing shared state and operations for the executor.

    This context is passed to operations when they execute, allowing them
    to access shared resources like the event queue and active sessions.
    """

    def __init__(
        self,
        event_queue: asyncio.Queue[events.Event],
        llm_client: LLMClientABC,
        llm_config: llm_parameter.LLMConfigParameter,
        debug_mode: bool = False,
    ):
        self.event_queue = event_queue
        self.llm_client = llm_client
        self.llm_config = llm_config
        self.debug_mode = debug_mode

        # Track active agents by session ID
        self.active_agents: dict[str, Agent] = {}
        # Track active tasks by submission ID
        self.active_tasks: dict[str, asyncio.Task[None]] = {}
        # Track which session a task belongs to (submission ID -> session ID)
        self.active_task_sessions: dict[str, str] = {}

    async def emit_event(self, event: events.Event) -> None:
        """Emit an event to the UI display system."""
        await self.event_queue.put(event)

    async def handle_init_agent(self, operation: InitAgentOperation) -> None:
        """Initialize an agent for a session and replay history to UI."""
        session_key = operation.session_id or "default"
        # Create agent if not exists
        if session_key not in self.active_agents:
            system_prompt = get_system_prompt(self.llm_client.model_name())
            if session_key == "default":
                session = Session(work_dir=Path.cwd(), system_prompt=system_prompt)
            else:
                session = Session.load(session_key, system_prompt=system_prompt)
            agent = Agent(
                llm_client=self.llm_client,
                session=session,
                tools=get_tool_schemas(
                    [TODO_WRITE_TOOL_NAME, BASH_TOOL_NAME, READ_TOOL_NAME, EDIT_TOOL_NAME, MULTI_EDIT_TOOL_NAME]
                ),
                debug_mode=self.debug_mode,
                reminders=[
                    empty_todo_reminder,
                    todo_not_used_recently_reminder,
                    file_changed_externally_reminder,
                    memory_reminder,
                    last_path_memory_reminder,
                ],
            )
            async for evt in agent.replay_history():
                await self.emit_event(evt)
            await self.emit_event(
                events.WelcomeEvent(
                    work_dir=str(session.work_dir),
                    llm_config=self.llm_config,
                )
            )
            self.active_agents[session_key] = agent
            if self.debug_mode:
                log_debug(f"Initialized agent for session: {session.id}", style="cyan")

    async def handle_user_input(self, operation: UserInputOperation) -> None:
        """Handle a user input operation by running it through an agent."""

        session_key = operation.session_id or "default"
        # Ensure initialized via init_agent
        if session_key not in self.active_agents:
            await self.handle_init_agent(InitAgentOperation(id=str(uuid4()), session_id=operation.session_id))

        agent = self.active_agents[session_key]
        actual_session_id = agent.session.id

        # emit user input event
        await self.emit_event(events.UserMessageEvent(content=operation.content, session_id=actual_session_id))

        # Start task to process user input (do NOT await here so the executor loop stays responsive)
        task: asyncio.Task[None] = asyncio.create_task(
            self._run_agent_task(agent, operation.content, operation.id, actual_session_id)
        )
        self.active_tasks[operation.id] = task
        self.active_task_sessions[operation.id] = actual_session_id
        # Do not await task here; completion will be tracked by the executor

    async def handle_interrupt(self, operation: InterruptOperation) -> None:
        """Handle an interrupt by invoking agent.cancel() and cancelling tasks."""

        # Determine affected sessions
        if operation.target_session_id is not None:
            session_ids: list[str] = [operation.target_session_id]
        else:
            session_ids = list(self.active_agents.keys())

        # Call cancel() on each affected agent to persist an interrupt marker
        for sid in session_ids:
            agent = self.active_agents.get(sid)
            if agent is not None:
                agent.cancel()

        # emit interrupt event
        await self.emit_event(events.InterruptEvent(session_id=operation.target_session_id or "all"))

        # Find tasks to cancel (filter by target sessions if provided)
        tasks_to_cancel: list[tuple[str, asyncio.Task[None]]] = []
        for task_id, task in list(self.active_tasks.items()):
            if task.done():
                continue
            if operation.target_session_id is None:
                tasks_to_cancel.append((task_id, task))
            else:
                if self.active_task_sessions.get(task_id) == operation.target_session_id:
                    tasks_to_cancel.append((task_id, task))

        if self.debug_mode:
            scope = operation.target_session_id or "all"
            log_debug(f"Interrupting {len(tasks_to_cancel)} task(s) for: {scope}", style="yellow")

        # Cancel the tasks
        for task_id, task in tasks_to_cancel:
            task.cancel()
            # Remove from active tasks immediately
            self.active_tasks.pop(task_id, None)
            self.active_task_sessions.pop(task_id, None)

        # Emit interrupt confirmation event if needed
        if tasks_to_cancel:
            await self.emit_event(events.TaskFinishEvent(session_id=operation.target_session_id or "all"))

    async def _run_agent_task(self, agent: Agent, user_input: str, task_id: str, session_id: str) -> None:
        """
        Run an agent task and forward all events to the UI.

        This method wraps the agent's run_task method and handles any exceptions
        that might occur during execution.
        """
        try:
            if self.debug_mode:
                log_debug(f"Starting agent task {task_id} for session {session_id}", style="green")

            # Forward all events from the agent to the UI
            async for event in agent.run_task(user_input):
                await self.emit_event(event)

        except asyncio.CancelledError:
            # Task was cancelled (likely due to interrupt)
            if self.debug_mode:
                log_debug(f"Agent task {task_id} was cancelled", style="yellow")
            await self.emit_event(events.TaskFinishEvent(session_id=session_id))

        except Exception as e:
            # Handle any other exceptions
            if self.debug_mode:
                log_debug(f"Agent task {task_id} failed: {str(e)}", style="red")
            await self.emit_event(events.ErrorEvent(error_message=f"Agent task failed: {str(e)}"))

        finally:
            # Clean up the task from active tasks
            self.active_tasks.pop(task_id, None)
            self.active_task_sessions.pop(task_id, None)
            if self.debug_mode:
                log_debug(f"Cleaned up agent task {task_id}", style="cyan")


class Executor:
    """
    Core executor that processes operations submitted from the CLI.

    This class implements a message loop similar to Codex-rs's submission_loop,
    processing operations asynchronously and coordinating with agents.
    """

    def __init__(
        self,
        event_queue: asyncio.Queue[events.Event],
        llm_client: LLMClientABC,
        llm_config: llm_parameter.LLMConfigParameter,
        debug_mode: bool = False,
    ):
        self.context = ExecutorContext(event_queue, llm_client, llm_config, debug_mode)
        self.submission_queue: asyncio.Queue[Submission] = asyncio.Queue()
        self.running = False
        self.debug_mode = debug_mode
        self.task_completion_events: dict[str, asyncio.Event] = {}

    async def submit(self, operation_data: dict[str, Any]) -> str:
        """
        Submit an operation to the executor for processing.

        Args:
            operation_data: Dictionary containing operation type and parameters

        Returns:
            Unique submission ID for tracking
        """
        submission_id = str(uuid4())

        # Create the appropriate operation based on type
        op_type = cast(str | None, operation_data.get("type"))
        if op_type == "user_input":
            content = cast(str, operation_data["content"])  # required
            session_id = cast(str | None, operation_data.get("session_id"))
            operation = UserInputOperation(id=submission_id, content=content, session_id=session_id)
        elif op_type == "interrupt":
            target_session_id = cast(str | None, operation_data.get("target_session_id"))
            operation = InterruptOperation(id=submission_id, target_session_id=target_session_id)
        elif op_type == "init_agent":
            session_id = cast(str | None, operation_data.get("session_id"))
            operation = InitAgentOperation(id=submission_id, session_id=session_id)
        else:
            raise ValueError(f"Unsupported operation type: {op_type}")

        submission = Submission(id=submission_id, operation=operation)
        await self.submission_queue.put(submission)

        # Create completion event for tracking
        completion_event = asyncio.Event()
        self.task_completion_events[submission_id] = completion_event

        if self.debug_mode:
            log_debug(f"Submitted operation {op_type} with ID {submission_id}", style="blue")

        return submission_id

    async def wait_for_completion(self, submission_id: str) -> None:
        """Wait for a specific submission to complete."""
        if submission_id in self.task_completion_events:
            await self.task_completion_events[submission_id].wait()
            # Clean up the completion event
            self.task_completion_events.pop(submission_id, None)

    async def start(self) -> None:
        """
        Start the executor main loop.

        This method runs continuously, processing submissions from the queue
        until the executor is stopped.
        """
        self.running = True

        if self.debug_mode:
            log_debug("Executor started", style="green")

        while self.running:
            try:
                # Wait for next submission
                submission = await self.submission_queue.get()
                await self._handle_submission(submission)

            except asyncio.CancelledError:
                # Executor was cancelled
                if self.debug_mode:
                    log_debug("Executor cancelled", style="yellow")
                break

            except Exception as e:
                # Handle unexpected errors
                if self.debug_mode:
                    log_debug(f"Executor error: {str(e)}", style="red")
                await self.context.emit_event(events.ErrorEvent(error_message=f"Executor error: {str(e)}"))

    async def stop(self) -> None:
        """Stop the executor and clean up resources."""
        self.running = False

        # Cancel all active tasks
        for task in self.context.active_tasks.values():
            if not task.done():
                task.cancel()

        if self.debug_mode:
            log_debug("Executor stopped", style="yellow")

    async def _handle_submission(self, submission: Submission) -> None:
        """
        Handle a single submission by executing its operation.

        This method delegates to the operation's execute method, which
        can access shared resources through the executor context.
        """
        try:
            if self.debug_mode:
                log_debug(
                    f"Handling submission {submission.id} of type {submission.operation.type.value}", style="cyan"
                )

            # For user_input, execute quickly to spawn the agent task, then track completion
            if submission.operation.type == OperationType.USER_INPUT:
                # Execute to spawn the agent task in context
                await submission.operation.execute(self.context)

                async def _await_agent_and_complete() -> None:
                    try:
                        # Wait for the agent task tied to this submission id
                        task = self.context.active_tasks.get(submission.id)
                        if task is not None:
                            await task
                    finally:
                        # Signal completion of this submission when agent task completes
                        if submission.id in self.task_completion_events:
                            self.task_completion_events[submission.id].set()

                # Run in background so the submission loop can continue (e.g., to handle interrupts)
                asyncio.create_task(_await_agent_and_complete())
            else:
                # Delegate to the operation's execute method (completes within this call)
                await submission.operation.execute(self.context)

        except Exception as e:
            if self.debug_mode:
                log_debug(f"Failed to handle submission {submission.id}: {str(e)}", style="red")
            await self.context.emit_event(events.ErrorEvent(error_message=f"Operation failed: {str(e)}"))
        finally:
            # For non-user_input, mark completion now; for user_input, completion is set when agent task ends
            if submission.operation.type != OperationType.USER_INPUT:
                if submission.id in self.task_completion_events:
                    self.task_completion_events[submission.id].set()
