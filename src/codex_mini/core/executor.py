"""
Executor module providing the core event loop and task management.

This module implements the submission_loop equivalent for codex-mini,
handling operations submitted from the CLI and coordinating with agents.
"""

import asyncio
from typing import Any, cast
from uuid import uuid4

from codex_mini.core.agent import Agent
from codex_mini.core.prompt import get_system_prompt
from codex_mini.core.tool import BASH_TOOL_NAME, get_tool_schemas
from codex_mini.llm.client import LLMClientABC
from codex_mini.protocol.events import ErrorEvent, Event, TaskFinishEvent
from codex_mini.protocol.operations import InterruptOperation, Submission, UserInputOperation
from codex_mini.trace import log_debug


class ExecutorContext:
    """
    Context object providing shared state and operations for the executor.

    This context is passed to operations when they execute, allowing them
    to access shared resources like the event queue and active sessions.
    """

    def __init__(self, event_queue: asyncio.Queue[Event], llm_client: LLMClientABC, debug_mode: bool = False):
        self.event_queue = event_queue
        self.llm_client = llm_client
        self.debug_mode = debug_mode

        # Track active agents by session ID
        self.active_agents: dict[str, Agent] = {}
        # Track active tasks by submission ID
        self.active_tasks: dict[str, asyncio.Task[None]] = {}

    async def emit_event(self, event: Event) -> None:
        """Emit an event to the UI display system."""
        await self.event_queue.put(event)

    async def handle_user_input(self, operation: UserInputOperation) -> None:
        """Handle a user input operation by running it through an agent."""
        session_id = operation.session_id or "default"

        # Get or create agent for this session
        if session_id not in self.active_agents:
            agent = Agent(
                llm_client=self.llm_client,
                session_id=session_id,
                tools=get_tool_schemas([BASH_TOOL_NAME]),
                system_prompt=get_system_prompt(self.llm_client.model_name()),
                debug_mode=self.debug_mode,
            )
            self.active_agents[session_id] = agent

            if self.debug_mode:
                log_debug(f"Created new agent for session: {session_id}", style="cyan")

        agent = self.active_agents[session_id]

        # Start task to process user input and wait for it to complete
        task: asyncio.Task[None] = asyncio.create_task(
            self._run_agent_task(agent, operation.content, operation.id, session_id)
        )
        self.active_tasks[operation.id] = task

        # Wait for the agent task to complete
        await task

    async def handle_interrupt(self, operation: InterruptOperation) -> None:
        """Handle an interrupt operation by cancelling active tasks."""

        tasks_to_cancel: list[tuple[str, asyncio.Task[None]]] = []
        if operation.target_session_id:
            # Interrupt tasks for specific session
            for task_id, task in self.active_tasks.items():
                # Find tasks belonging to the target session
                # (We could store session mapping separately for more efficiency)
                if not task.done():
                    tasks_to_cancel.append((task_id, task))

            if self.debug_mode:
                log_debug(
                    f"Interrupting {len(tasks_to_cancel)} tasks for session: {operation.target_session_id}",
                    style="yellow",
                )
        else:
            # Interrupt all active tasks
            tasks_to_cancel = [(task_id, task) for task_id, task in self.active_tasks.items() if not task.done()]

            if self.debug_mode:
                log_debug(f"Interrupting all {len(tasks_to_cancel)} active tasks", style="yellow")

        # Cancel the tasks
        for task_id, task in tasks_to_cancel:
            task.cancel()
            # Remove from active tasks immediately
            self.active_tasks.pop(task_id, None)

        # Emit interrupt confirmation event if needed
        if tasks_to_cancel:
            await self.emit_event(TaskFinishEvent(session_id=operation.target_session_id or "all"))

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
            await self.emit_event(TaskFinishEvent(session_id=session_id))

        except Exception as e:
            # Handle any other exceptions
            if self.debug_mode:
                log_debug(f"Agent task {task_id} failed: {str(e)}", style="red")
            await self.emit_event(ErrorEvent(error_message=f"Agent task failed: {str(e)}"))

        finally:
            # Clean up the task from active tasks
            self.active_tasks.pop(task_id, None)
            if self.debug_mode:
                log_debug(f"Cleaned up agent task {task_id}", style="cyan")


class Executor:
    """
    Core executor that processes operations submitted from the CLI.

    This class implements a message loop similar to Codex-rs's submission_loop,
    processing operations asynchronously and coordinating with agents.
    """

    def __init__(self, event_queue: asyncio.Queue[Event], llm_client: LLMClientABC, debug_mode: bool = False):
        self.context = ExecutorContext(event_queue, llm_client, debug_mode)
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
                await self.context.emit_event(ErrorEvent(error_message=f"Executor error: {str(e)}"))

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

            # Delegate to the operation's execute method
            await submission.operation.execute(self.context)

        except Exception as e:
            if self.debug_mode:
                log_debug(f"Failed to handle submission {submission.id}: {str(e)}", style="red")
            await self.context.emit_event(ErrorEvent(error_message=f"Operation failed: {str(e)}"))
        finally:
            # Signal completion of this submission
            if submission.id in self.task_completion_events:
                self.task_completion_events[submission.id].set()
