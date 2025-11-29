"""
Executor module providing the core event loop and task management.

This module implements the submission_loop equivalent for klaude,
handling operations submitted from the CLI and coordinating with agents.
"""

import asyncio
from dataclasses import dataclass

from klaude_code.command import dispatch_command
from klaude_code.core.agent import Agent, DefaultModelProfileProvider, ModelProfileProvider
from klaude_code.core.sub_agent import SubAgentResult
from klaude_code.core.tool import current_run_subtask_callback
from klaude_code.llm import LLMClients
from klaude_code.protocol import events, model, op
from klaude_code.session.session import Session
from klaude_code.trace import DebugType, log_debug


@dataclass
class ActiveTask:
    """Track an in-flight task and its owning session."""

    task: asyncio.Task[None]
    session_id: str


class ExecutorContext:
    """
    Context object providing shared state and operations for the executor.

    This context is passed to operations when they execute, allowing them
    to access shared resources like the event queue and active sessions.
    """

    def __init__(
        self,
        event_queue: asyncio.Queue[events.Event],
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider | None = None,
    ):
        self.event_queue: asyncio.Queue[events.Event] = event_queue
        self.llm_clients: LLMClients = llm_clients
        self.model_profile_provider: ModelProfileProvider = model_profile_provider or DefaultModelProfileProvider()

        # Track active agents by session ID
        self.active_agents: dict[str, Agent] = {}
        # Track active tasks by submission ID, retaining owning session for filtering/cancellation
        self.active_tasks: dict[str, ActiveTask] = {}

    async def emit_event(self, event: events.Event) -> None:
        """Emit an event to the UI display system."""
        await self.event_queue.put(event)

    async def _ensure_agent(self, session_id: str) -> Agent:
        """Return an existing agent for the session or create a new one."""

        agent = self.active_agents.get(session_id)
        if agent is not None:
            return agent

        session = Session.load(session_id)
        profile = self.model_profile_provider.build_profile(self.llm_clients.main)
        agent = Agent(
            session=session,
            profile=profile,
            model_profile_provider=self.model_profile_provider,
        )

        async for evt in agent.replay_history():
            await self.emit_event(evt)

        await self.emit_event(
            events.WelcomeEvent(
                work_dir=str(session.work_dir),
                llm_config=self.llm_clients.main.get_llm_config(),
            )
        )

        self.active_agents[session_id] = agent
        log_debug(
            f"Initialized agent for session: {session_id}",
            style="cyan",
            debug_type=DebugType.EXECUTION,
        )
        return agent

    async def handle_init_agent(self, operation: op.InitAgentOperation) -> None:
        """Initialize an agent for a session and replay history to UI."""
        if operation.session_id is None:
            raise ValueError("session_id cannot be None")

        await self._ensure_agent(operation.session_id)

    async def handle_user_input(self, operation: op.UserInputOperation) -> None:
        """Handle a user input operation by running it through an agent."""

        if operation.session_id is None:
            raise ValueError("session_id cannot be None")

        session_id = operation.session_id
        agent = await self._ensure_agent(session_id)
        user_input = operation.input

        # emit user input event
        await self.emit_event(
            events.UserMessageEvent(content=user_input.text, session_id=session_id, images=user_input.images)
        )

        result = await dispatch_command(user_input.text, agent)
        if not result.agent_input:
            # If this command do not need run agent, we should append user message to session history here
            agent.session.append_history([model.UserMessageItem(content=user_input.text, images=user_input.images)])

        if result.events:
            agent.session.append_history(
                [evt.item for evt in result.events if isinstance(evt, events.DeveloperMessageEvent)]
            )
            for evt in result.events:
                await self.emit_event(evt)

        if result.agent_input:
            # Construct new UserInputPayload with command-processed text, preserving original images
            task_input = model.UserInputPayload(text=result.agent_input, images=user_input.images)
            # Start task to process user input (do NOT await here so the executor loop stays responsive)
            task: asyncio.Task[None] = asyncio.create_task(
                self._run_agent_task(agent, task_input, operation.id, session_id)
            )
            self.active_tasks[operation.id] = ActiveTask(task=task, session_id=session_id)
            # Do not await task here; completion will be tracked by the executor

    async def handle_interrupt(self, operation: op.InterruptOperation) -> None:
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
                for evt in agent.cancel():
                    await self.emit_event(evt)

        # emit interrupt event
        await self.emit_event(events.InterruptEvent(session_id=operation.target_session_id or "all"))

        # Find tasks to cancel (filter by target sessions if provided)
        tasks_to_cancel: list[tuple[str, asyncio.Task[None]]] = []
        for task_id, active in list(self.active_tasks.items()):
            task = active.task
            if task.done():
                continue
            if operation.target_session_id is None:
                tasks_to_cancel.append((task_id, task))
            else:
                if active.session_id == operation.target_session_id:
                    tasks_to_cancel.append((task_id, task))

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
            self.active_tasks.pop(task_id, None)

    async def _run_agent_task(
        self, agent: Agent, user_input: model.UserInputPayload, task_id: str, session_id: str
    ) -> None:
        """
        Run an agent task and forward all events to the UI.

        This method wraps the agent's run_task method and handles any exceptions
        that might occur during execution.
        """
        try:
            log_debug(
                f"Starting agent task {task_id} for session {session_id}",
                style="green",
                debug_type=DebugType.EXECUTION,
            )

            # Inject subtask runner into tool context for nested Task tool usage
            async def _runner(state: model.SubAgentState) -> SubAgentResult:
                return await self._run_subagent_task(agent, state)

            token = current_run_subtask_callback.set(_runner)
            try:
                # Forward all events from the agent to the UI
                async for event in agent.run_task(user_input):
                    await self.emit_event(event)
            finally:
                current_run_subtask_callback.reset(token)

        except asyncio.CancelledError:
            # Task was cancelled (likely due to interrupt)
            log_debug(
                f"Agent task {task_id} was cancelled",
                style="yellow",
                debug_type=DebugType.EXECUTION,
            )
            await self.emit_event(events.TaskFinishEvent(session_id=session_id, task_result="task cancelled"))

        except Exception as e:
            # Handle any other exceptions
            import traceback

            log_debug(
                f"Agent task {task_id} failed: {str(e)}",
                style="red",
                debug_type=DebugType.EXECUTION,
            )
            log_debug(traceback.format_exc(), style="red", debug_type=DebugType.EXECUTION)
            await self.emit_event(
                events.ErrorEvent(
                    error_message=f"Agent task failed: [{e.__class__.__name__}] {str(e)}",
                    can_retry=False,
                )
            )

        finally:
            # Clean up the task from active tasks
            self.active_tasks.pop(task_id, None)
            log_debug(
                f"Cleaned up agent task {task_id}",
                style="cyan",
                debug_type=DebugType.EXECUTION,
            )

    async def _run_subagent_task(self, parent_agent: Agent, state: model.SubAgentState) -> SubAgentResult:
        """Run a nested sub-agent task and return the final task_result text.

        - Creates a child session linked to the parent session
        - Streams the child agent's events to the same event queue
        - Returns the last assistant message content as the result
        """
        # Create a child session under the same workdir
        parent_session = parent_agent.session
        child_session = Session(work_dir=parent_session.work_dir)
        child_session.sub_agent_state = state

        child_profile = self.model_profile_provider.build_profile(
            self.llm_clients.get_client(state.sub_agent_type),
            state.sub_agent_type,
        )
        child_agent = Agent(
            session=child_session,
            profile=child_profile,
            model_profile_provider=self.model_profile_provider,
        )

        log_debug(
            f"Running sub-agent {state.sub_agent_type} in session {child_session.id}",
            style="cyan",
            debug_type=DebugType.EXECUTION,
        )

        try:
            # Not emit the subtask's user input since task tool call is already rendered
            result: str = ""
            sub_agent_input = model.UserInputPayload(text=state.sub_agent_prompt, images=None)
            async for event in child_agent.run_task(sub_agent_input):
                # Capture TaskFinishEvent content for return
                if isinstance(event, events.TaskFinishEvent):
                    result = event.task_result
                await self.emit_event(event)
            return SubAgentResult(task_result=result, session_id=child_session.id)
        except asyncio.CancelledError:
            # Propagate cancellation so tooling can treat it as user interrupt
            log_debug(
                f"Subagent task for {state.sub_agent_type} was cancelled",
                style="yellow",
                debug_type=DebugType.EXECUTION,
            )
            raise
        except Exception as e:
            log_debug(
                f"Subagent task failed: [{e.__class__.__name__}] {str(e)}",
                style="red",
                debug_type=DebugType.EXECUTION,
            )
            return SubAgentResult(
                task_result=f"Subagent task failed: [{e.__class__.__name__}] {str(e)}",
                session_id="",
                error=True,
            )


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
    ):
        self.context = ExecutorContext(event_queue, llm_clients, model_profile_provider)
        self.submission_queue: asyncio.Queue[op.Submission] = asyncio.Queue()
        # Track completion events for all submissions (not just those with ActiveTask)
        self._completion_events: dict[str, asyncio.Event] = {}

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
                    f"Executor error: {str(e)}",
                    style="red",
                    debug_type=DebugType.EXECUTION,
                )
                await self.context.emit_event(
                    events.ErrorEvent(error_message=f"Executor error: {str(e)}", can_retry=False)
                )

    async def stop(self) -> None:
        """Stop the executor and clean up resources."""
        # Cancel all active tasks and collect them for awaiting
        tasks_to_await: list[asyncio.Task[None]] = []
        for active in self.context.active_tasks.values():
            task = active.task
            if not task.done():
                task.cancel()
                tasks_to_await.append(task)

        # Wait for all cancelled tasks to complete
        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)

        # Clear the active_tasks dictionary
        self.context.active_tasks.clear()

        # Send EndOperation to wake up the start() loop
        try:
            end_operation = op.EndOperation()
            submission = op.Submission(id=end_operation.id, operation=end_operation)
            await self.submission_queue.put(submission)
        except Exception as e:
            log_debug(
                f"Failed to send EndOperation: {str(e)}",
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
            await submission.operation.execute(self.context)

            async def _await_agent_and_complete() -> None:
                # Wait for the agent task tied to this submission id
                active = self.context.active_tasks.get(submission.id)
                if active is not None:
                    try:
                        await active.task
                    finally:
                        event = self._completion_events.get(submission.id)
                        if event is not None:
                            event.set()

            # Run in background so the submission loop can continue (e.g., to handle interrupts)
            asyncio.create_task(_await_agent_and_complete())

            # For operations without ActiveTask (e.g., InitAgentOperation), signal completion immediately
            if submission.id not in self.context.active_tasks:
                event = self._completion_events.get(submission.id)
                if event is not None:
                    event.set()

        except Exception as e:
            log_debug(
                f"Failed to handle submission {submission.id}: {str(e)}",
                style="red",
                debug_type=DebugType.EXECUTION,
            )
            await self.context.emit_event(
                events.ErrorEvent(error_message=f"Operation failed: {str(e)}", can_retry=False)
            )
            # Set completion event even on error to prevent wait_for_completion from hanging
            event = self._completion_events.get(submission.id)
            if event is not None:
                event.set()
