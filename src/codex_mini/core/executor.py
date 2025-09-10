"""
Executor module providing the core event loop and task management.

This module implements the submission_loop equivalent for codex-mini,
handling operations submitted from the CLI and coordinating with agents.
"""

import asyncio
from pathlib import Path
from uuid import uuid4

from codex_mini.command import dispatch_command
from codex_mini.core.agent import Agent, AgentLLMClients
from codex_mini.core.reminders import (
    at_file_reader_reminder,
    empty_todo_reminder,
    file_changed_externally_reminder,
    last_path_memory_reminder,
    memory_reminder,
    todo_not_used_recently_reminder,
    plan_mode_reminder,
)
from codex_mini.core.tool import get_tool_schemas
from codex_mini.core.tool.tool_context import current_run_subtask_callback
from codex_mini.protocol import events, llm_parameter, model, tools
from codex_mini.protocol.op import InitAgentOperation, InterruptOperation, Operation, Submission, UserInputOperation
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
        llm_clients: AgentLLMClients,
        llm_config: llm_parameter.LLMConfigParameter,
        debug_mode: bool = False,
    ):
        self.event_queue = event_queue
        self.llm_clients = llm_clients
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
            if session_key == "default":
                session = Session(work_dir=Path.cwd())
            else:
                session = Session.load(session_key)
            agent = Agent(
                llm_clients=self.llm_clients,
                session=session,
                tools=get_tool_schemas(
                    [
                        tools.TODO_WRITE,
                        tools.BASH,
                        tools.READ,
                        tools.EDIT,
                        tools.MULTI_EDIT,
                        tools.EXIT_PLAN_MODE,
                        tools.TASK,
                    ]
                ),
                debug_mode=self.debug_mode,
                reminders=[
                    empty_todo_reminder,
                    todo_not_used_recently_reminder,
                    file_changed_externally_reminder,
                    memory_reminder,
                    last_path_memory_reminder,
                    at_file_reader_reminder,
                    plan_mode_reminder,
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
        await self.event_queue.join()

        result = await dispatch_command(operation.content, agent)
        if not result.agent_input:
            # If this command do not need run agent, we should append user message to session history here
            agent.session.append_history([model.UserMessageItem(content=operation.content)])

        if result.events:
            agent.session.append_history(
                [evt.item for evt in result.events if isinstance(evt, events.DeveloperMessageEvent)]
            )
            for evt in result.events:
                await self.emit_event(evt)

        if result.agent_input:
            # Start task to process user input (do NOT await here so the executor loop stays responsive)
            task: asyncio.Task[None] = asyncio.create_task(
                self._run_agent_task(agent, result.agent_input, operation.id, actual_session_id)
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
            await self.emit_event(
                events.TaskFinishEvent(session_id=operation.target_session_id or "all", task_result="task cancelled")
            )

    async def _run_agent_task(self, agent: Agent, user_input: str, task_id: str, session_id: str) -> None:
        """
        Run an agent task and forward all events to the UI.

        This method wraps the agent's run_task method and handles any exceptions
        that might occur during execution.
        """
        try:
            if self.debug_mode:
                log_debug(f"Starting agent task {task_id} for session {session_id}", style="green")

            # Inject subtask runner into tool context for nested Task tool usage
            async def _runner(prompt: str) -> str:
                return await self._run_subagent_task(agent, prompt)

            token = current_run_subtask_callback.set(_runner)
            try:
                # Forward all events from the agent to the UI
                async for event in agent.run_task(user_input):
                    await self.emit_event(event)
            finally:
                current_run_subtask_callback.reset(token)

        except asyncio.CancelledError:
            # Task was cancelled (likely due to interrupt)
            if self.debug_mode:
                log_debug(f"Agent task {task_id} was cancelled", style="yellow")
            await self.emit_event(events.TaskFinishEvent(session_id=session_id, task_result="task cancelled"))

        except Exception as e:
            # Handle any other exceptions
            if self.debug_mode:
                import traceback

                log_debug(f"Agent task {task_id} failed: {str(e)}", style="red")
                log_debug(traceback.format_exc(), style="red")
            await self.emit_event(
                events.ErrorEvent(error_message=f"Agent task failed: [{e.__class__.__name__}] {str(e)}")
            )

        finally:
            # Clean up the task from active tasks
            self.active_tasks.pop(task_id, None)
            self.active_task_sessions.pop(task_id, None)
            if self.debug_mode:
                log_debug(f"Cleaned up agent task {task_id}", style="cyan")

    async def _run_subagent_task(self, parent_agent: Agent, prompt: str) -> str:
        """Run a nested sub-agent task and return the final task_result text.

        - Creates a child session linked to the parent session
        - Streams the child agent's events to the same event queue
        - Returns the last assistant message content as the result
        """
        # Create a child session under the same workdir
        parent_session = parent_agent.session
        child_session = Session(work_dir=parent_session.work_dir)
        child_session.is_root_session = False
        # Link relationship and persist parent change
        parent_session.child_session_ids.append(child_session.id)
        parent_session.save()

        # Build a fresh AgentLLMClients wrapper to avoid mutating parent's pointers
        child_llm_clients = AgentLLMClients(
            main=self.llm_clients.task or self.llm_clients.main, fast=self.llm_clients.fast
        )

        child_agent = Agent(
            llm_clients=child_llm_clients,
            session=child_session,
            tools=get_tool_schemas(
                [
                    tools.BASH,
                    tools.READ,
                    tools.EDIT,
                    tools.MULTI_EDIT,
                ]
            ),
            debug_mode=self.debug_mode,
            reminders=[
                file_changed_externally_reminder,
                memory_reminder,
                last_path_memory_reminder,
                at_file_reader_reminder,
            ],
        )

        try:
            # Not emit the subtask's user input since task tool call is already rendered
            result: str = ""
            async for event in child_agent.run_task(prompt):
                # Capture TaskFinishEvent content for return
                if isinstance(event, events.TaskFinishEvent):
                    result = event.task_result
                    break  # Subagent cannot nested
                await self.emit_event(event)
            return result
        except Exception as e:
            log_debug(f"Subagent task failed: [{e.__class__.__name__}] {str(e)}", style="red")
            return f"Subagent task failed: [{e.__class__.__name__}] {str(e)}"


class Executor:
    """
    Core executor that processes operations submitted from the CLI.

    This class implements a message loop similar to Codex-rs's submission_loop,
    processing operations asynchronously and coordinating with agents.
    """

    def __init__(
        self,
        event_queue: asyncio.Queue[events.Event],
        llm_clients: AgentLLMClients,
        llm_config: llm_parameter.LLMConfigParameter,
        debug_mode: bool = False,
    ):
        self.context = ExecutorContext(event_queue, llm_clients, llm_config, debug_mode)
        self.submission_queue: asyncio.Queue[Submission] = asyncio.Queue()
        self.running = False
        self.debug_mode = debug_mode
        self.task_completion_events: dict[str, asyncio.Event] = {}

    async def submit(self, operation: Operation) -> str:
        """
        Submit an operation to the executor for processing.

        Args:
            operation: Operation to submit

        Returns:
            Unique submission ID for tracking
        """

        submission = Submission(id=operation.id, operation=operation)
        await self.submission_queue.put(submission)

        # Create completion event for tracking
        completion_event = asyncio.Event()
        self.task_completion_events[operation.id] = completion_event

        if self.debug_mode:
            log_debug(f"Submitted operation {operation.type} with ID {operation.id}", style="blue")

        return operation.id

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

        except Exception as e:
            if self.debug_mode:
                log_debug(f"Failed to handle submission {submission.id}: {str(e)}", style="red")
            await self.context.emit_event(events.ErrorEvent(error_message=f"Operation failed: {str(e)}"))
            # Set completion event even on error to prevent wait_for_completion from hanging
            completion_event = self.task_completion_events.get(submission.id)
            if completion_event is not None:
                completion_event.set()
