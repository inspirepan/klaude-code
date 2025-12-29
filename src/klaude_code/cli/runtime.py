import asyncio
import contextlib
import sys
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

import typer
from rich.text import Text

from klaude_code import ui
from klaude_code.cli.main import update_terminal_title
from klaude_code.cli.self_update import get_update_message
from klaude_code.command import dispatch_command, get_command_info_list, has_interactive_command, is_slash_command_name
from klaude_code.config import Config, load_config
from klaude_code.core.agent import Agent, DefaultModelProfileProvider, VanillaModelProfileProvider
from klaude_code.core.executor import Executor
from klaude_code.core.manager import build_llm_clients
from klaude_code.protocol import events, llm_param, op
from klaude_code.protocol import model as protocol_model
from klaude_code.protocol.model import UserInputPayload
from klaude_code.session.session import Session, close_default_store
from klaude_code.trace import DebugType, log, set_debug_logging
from klaude_code.ui.modes.repl import build_repl_status_snapshot
from klaude_code.ui.modes.repl.input_prompt_toolkit import REPLStatusSnapshot
from klaude_code.ui.terminal.color import is_light_terminal_background
from klaude_code.ui.terminal.control import install_sigint_double_press_exit, start_esc_interrupt_monitor
from klaude_code.ui.terminal.progress_bar import OSC94States, emit_osc94


class PrintCapable(Protocol):
    """Protocol for objects that can print styled content."""

    def print(self, *objects: Any, style: Any | None = None, end: str = "\n") -> None: ...


@dataclass
class AppInitConfig:
    """Configuration for initializing the application components."""

    model: str | None
    debug: bool
    vanilla: bool
    is_exec_mode: bool = False
    debug_filters: set[DebugType] | None = None
    stream_json: bool = False


@dataclass
class AppComponents:
    """Initialized application components."""

    config: Config
    executor: Executor
    executor_task: asyncio.Task[None]
    event_queue: asyncio.Queue[events.Event]
    display: ui.DisplayABC
    display_task: asyncio.Task[None]
    theme: str | None


async def submit_user_input_payload(
    *,
    executor: Executor,
    event_queue: asyncio.Queue[events.Event],
    user_input: UserInputPayload,
    session_id: str | None,
) -> str | None:
    """Parse/dispatch a user input payload and submit resulting operations.

    The UI/CLI layer owns slash command parsing and any interactive prompts.
    Core only executes concrete operations.

    Returns a submission id that should be awaited, or None if there is nothing
    to wait for (e.g. commands that only emit events).
    """

    sid = session_id or executor.context.current_session_id()
    if sid is None:
        raise RuntimeError("No active session")

    agent = executor.context.current_agent
    if agent is None or agent.session.id != sid:
        await executor.submit_and_wait(op.InitAgentOperation(session_id=sid))
        agent = executor.context.current_agent

    if agent is None:
        raise RuntimeError("Failed to initialize agent")

    submission_id = uuid4().hex

    await executor.context.emit_event(
        events.UserMessageEvent(content=user_input.text, session_id=sid, images=user_input.images)
    )

    result = await dispatch_command(user_input, agent, submission_id=submission_id)
    operations: list[op.Operation] = list(result.operations or [])

    run_ops = [candidate for candidate in operations if isinstance(candidate, op.RunAgentOperation)]
    if len(run_ops) > 1:
        raise ValueError("Multiple RunAgentOperation results are not supported")

    persisted_user_input = run_ops[0].input if run_ops else user_input

    if result.persist_user_input:
        agent.session.append_history(
            [
                protocol_model.UserMessageItem(
                    content=persisted_user_input.text,
                    images=persisted_user_input.images,
                )
            ]
        )

    if result.events:
        for evt in result.events:
            if result.persist_events and isinstance(evt, events.DeveloperMessageEvent):
                agent.session.append_history([evt.item])
            await executor.context.emit_event(evt)

    submitted_ids: list[str] = []
    for operation_item in operations:
        submitted_ids.append(await executor.submit(operation_item))

    if not submitted_ids:
        # Ensure event-only commands are fully rendered before showing the next prompt.
        await event_queue.join()
        return None

    if run_ops:
        return run_ops[0].id
    return submitted_ids[-1]


async def initialize_app_components(init_config: AppInitConfig) -> AppComponents:
    """Initialize all application components (LLM clients, executor, UI)."""
    set_debug_logging(init_config.debug, filters=init_config.debug_filters)

    config = load_config()

    # Initialize LLM clients
    try:
        llm_clients = build_llm_clients(
            config,
            model_override=init_config.model,
        )
    except ValueError as exc:
        if init_config.model:
            log(
                (
                    f"Error: model '{init_config.model}' is not defined in the config",
                    "red",
                )
            )
            log(("Hint: run `klaude list` to view available models", "yellow"))
        else:
            log((f"Error: failed to load the default model configuration: {exc}", "red"))
        raise typer.Exit(2) from None

    model_profile_provider = VanillaModelProfileProvider() if init_config.vanilla else DefaultModelProfileProvider()

    # Create event queue for communication between executor and UI
    event_queue: asyncio.Queue[events.Event] = asyncio.Queue()

    # Create executor with the LLM client
    executor = Executor(
        event_queue,
        llm_clients,
        model_profile_provider=model_profile_provider,
        on_model_change=update_terminal_title,
    )

    # Update terminal title with initial model name
    update_terminal_title(llm_clients.main.model_name)

    # Start executor in background
    executor_task = asyncio.create_task(executor.start())

    theme: str | None = config.theme
    if theme is None and not init_config.is_exec_mode:
        # Auto-detect theme from terminal background when config does not specify a theme.
        # Skip detection in exec mode to avoid TTY race conditions with parent process's
        # ESC monitor when running as a subprocess.
        detected = is_light_terminal_background()
        if detected is True:
            theme = "light"
        elif detected is False:
            theme = "dark"

    # Set up UI components using factory functions
    display: ui.DisplayABC
    if init_config.is_exec_mode:
        display = ui.create_exec_display(debug=init_config.debug, stream_json=init_config.stream_json)
    else:
        display = ui.create_default_display(debug=init_config.debug, theme=theme)

    # Start UI display task
    display_task = asyncio.create_task(display.consume_event_loop(event_queue))

    return AppComponents(
        config=config,
        executor=executor,
        executor_task=executor_task,
        event_queue=event_queue,
        display=display,
        display_task=display_task,
        theme=theme,
    )


async def initialize_session(
    executor: Executor,
    event_queue: asyncio.Queue[events.Event],
    session_id: str | None = None,
) -> str | None:
    """Initialize a session and return the active session ID.

    Args:
        executor: The executor to submit operations to.
        event_queue: The event queue for synchronization.
        session_id: Optional session ID to resume. If None, creates a new session.

    Returns:
        The active session ID, or None if no session is active.
    """
    await executor.submit_and_wait(op.InitAgentOperation(session_id=session_id))
    await event_queue.join()

    active_session_id = executor.context.current_session_id()
    return active_session_id or session_id


def _backfill_session_model_config(
    agent: Agent | None,
    model_override: str | None,
    default_model: str | None,
    is_new_session: bool,
) -> None:
    """Backfill model_config_name and model_thinking on newly created sessions."""
    if agent is None or agent.session.model_config_name is not None:
        return

    if model_override is not None:
        agent.session.model_config_name = model_override
    elif is_new_session and default_model is not None:
        agent.session.model_config_name = default_model
    else:
        return

    if agent.session.model_thinking is None and agent.profile:
        agent.session.model_thinking = agent.profile.llm_client.get_llm_config().thinking
    # Don't save here - session will be saved when first message is sent via append_history()


async def cleanup_app_components(components: AppComponents) -> None:
    """Clean up all application components."""
    try:
        # Clean shutdown
        await components.executor.stop()
        components.executor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await components.executor_task
        with contextlib.suppress(Exception):
            await close_default_store()

        # Signal UI to stop
        await components.event_queue.put(events.EndEvent())
        await components.display_task
    finally:
        # Always attempt to clear Ghostty progress bar and restore cursor visibility
        # Best-effort only; never fail cleanup due to OSC errors
        with contextlib.suppress(Exception):
            emit_osc94(OSC94States.HIDDEN)

        # Ensure the terminal cursor is visible even if Rich's Status spinner
        # did not get a chance to stop cleanly (e.g. on KeyboardInterrupt).
        # If this fails the shell can still recover via `reset`/`stty sane`.
        with contextlib.suppress(Exception):
            stream = getattr(sys, "__stdout__", None) or sys.stdout
            stream.write("\033[?25h")
            stream.flush()


async def _handle_keyboard_interrupt(executor: Executor) -> None:
    """Handle Ctrl+C by logging and sending a global interrupt."""

    log("Bye!")
    session_id = executor.context.current_session_id()
    if session_id and Session.exists(session_id):
        log(("Resume with:", "dim"), (f"klaude --resume-by-id {session_id}", "green"))
    # Executor might already be stopping
    with contextlib.suppress(Exception):
        await executor.submit(op.InterruptOperation(target_session_id=None))


async def run_exec(init_config: AppInitConfig, input_content: str) -> None:
    """Run a single command non-interactively using the provided configuration."""

    components = await initialize_app_components(init_config)

    try:
        session_id = await initialize_session(components.executor, components.event_queue)
        _backfill_session_model_config(
            components.executor.context.current_agent,
            init_config.model,
            components.config.main_model,
            is_new_session=True,
        )

        wait_id = await submit_user_input_payload(
            executor=components.executor,
            event_queue=components.event_queue,
            user_input=UserInputPayload(text=input_content),
            session_id=session_id,
        )
        if wait_id is not None:
            await components.executor.wait_for(wait_id)
            await components.event_queue.join()

    except KeyboardInterrupt:
        await _handle_keyboard_interrupt(components.executor)
    finally:
        await cleanup_app_components(components)


async def run_interactive(init_config: AppInitConfig, session_id: str | None = None) -> None:
    """Run the interactive REPL using the provided configuration.

    If session_id is None, a new session is created with an auto-generated ID.
    If session_id is provided, attempts to resume that session.
    """
    components = await initialize_app_components(init_config)

    # No theme persistence from CLI anymore; config.theme controls theme when set.

    # Create status provider for bottom toolbar
    def _status_provider() -> REPLStatusSnapshot:
        update_message = get_update_message()
        return build_repl_status_snapshot(update_message)

    # Set up input provider for interactive mode
    def _stop_rich_bottom_ui() -> None:
        display = components.display
        if isinstance(display, ui.REPLDisplay):
            display.renderer.spinner_stop()
            display.renderer.stop_bottom_live()
        elif (
            isinstance(display, ui.DebugEventDisplay)
            and display.wrapped_display
            and isinstance(display.wrapped_display, ui.REPLDisplay)
        ):
            display.wrapped_display.renderer.spinner_stop()
            display.wrapped_display.renderer.stop_bottom_live()

    # Pass the pre-detected theme to avoid redundant TTY queries.
    # Querying the terminal background again after an interactive selection
    # can interfere with prompt_toolkit's terminal state and break history navigation.
    is_light_background: bool | None = None
    if components.theme == "light":
        is_light_background = True
    elif components.theme == "dark":
        is_light_background = False

    def _get_active_session_id() -> str | None:
        """Get the current active session ID dynamically.

        This is necessary because /clear command creates a new session with a different ID.
        """

        return components.executor.context.current_session_id()

    async def _change_model_from_prompt(model_name: str) -> None:
        sid = _get_active_session_id()
        if not sid:
            return
        await components.executor.submit_and_wait(
            op.ChangeModelOperation(
                session_id=sid,
                model_name=model_name,
                save_as_default=False,
                defer_thinking_selection=True,
                emit_welcome_event=False,
                emit_switch_message=False,
            )
        )

    def _get_current_llm_config() -> llm_param.LLMConfigParameter | None:
        agent = components.executor.context.current_agent
        if agent is None:
            return None
        return agent.profile.llm_client.get_llm_config()

    async def _change_thinking_from_prompt(thinking: llm_param.Thinking) -> None:
        sid = _get_active_session_id()
        if not sid:
            return
        await components.executor.submit_and_wait(
            op.ChangeThinkingOperation(
                session_id=sid,
                thinking=thinking,
                emit_welcome_event=False,
                emit_switch_message=False,
            )
        )

    # Inject command name checker into user_input renderer (for slash command highlighting)
    from klaude_code.ui.renderers.user_input import set_command_name_checker

    set_command_name_checker(is_slash_command_name)

    input_provider: ui.InputProviderABC = ui.PromptToolkitInput(
        status_provider=_status_provider,
        pre_prompt=_stop_rich_bottom_ui,
        is_light_background=is_light_background,
        get_current_model_config_name=lambda: (
            components.executor.context.current_agent.session.model_config_name
            if components.executor.context.current_agent is not None
            else None
        ),
        on_change_model=_change_model_from_prompt,
        get_current_llm_config=_get_current_llm_config,
        on_change_thinking=_change_thinking_from_prompt,
        command_info_provider=get_command_info_list,
    )

    # --- Custom Ctrl+C handler: double-press within 2s to exit, single press shows toast ---
    def _show_toast_once() -> None:
        MSG = "Press ctrl+c again to exit"
        try:
            # Keep message short; avoid interfering with spinner layout
            printer: PrintCapable | None = None

            # Check if it's a REPLDisplay with renderer
            if isinstance(components.display, ui.REPLDisplay):
                printer = components.display.renderer
            # Check if it's a DebugEventDisplay wrapping a REPLDisplay
            elif (
                isinstance(components.display, ui.DebugEventDisplay)
                and components.display.wrapped_display
                and isinstance(components.display.wrapped_display, ui.REPLDisplay)
            ):
                printer = components.display.wrapped_display.renderer

            if printer is not None:
                printer.print(Text(f" {MSG} ", style="bold yellow reverse"))
            else:
                print(MSG, file=sys.stderr)
        except (AttributeError, TypeError, RuntimeError):
            # Fallback if themed print is unavailable (e.g., display not ready or Rich internal error)
            print(MSG, file=sys.stderr)

    def _hide_progress() -> None:
        with contextlib.suppress(Exception):
            emit_osc94(OSC94States.HIDDEN)

    restore_sigint = install_sigint_double_press_exit(_show_toast_once, _hide_progress)

    exit_hint_printed = False

    try:
        await initialize_session(components.executor, components.event_queue, session_id=session_id)
        _backfill_session_model_config(
            components.executor.context.current_agent,
            init_config.model,
            components.config.main_model,
            is_new_session=session_id is None,
        )

        # Input
        await input_provider.start()
        async for user_input in input_provider.iter_inputs():
            # Handle special commands
            if user_input.text.strip().lower() in {"exit", ":q", "quit"}:
                break
            elif user_input.text.strip() == "":
                continue
            # Use dynamic session_id lookup to handle /clear creating new sessions.
            # UI/CLI parses commands and submits concrete operations; core executes operations.
            active_session_id = _get_active_session_id()
            is_interactive = has_interactive_command(user_input.text)

            wait_id = await submit_user_input_payload(
                executor=components.executor,
                event_queue=components.event_queue,
                user_input=user_input,
                session_id=active_session_id,
            )

            if wait_id is None:
                continue

            if is_interactive:
                await components.executor.wait_for(wait_id)
                continue

            # Esc monitor for long-running, interruptible operations
            async def _on_esc_interrupt() -> None:
                await components.executor.submit(op.InterruptOperation(target_session_id=_get_active_session_id()))

            stop_event, esc_task = start_esc_interrupt_monitor(_on_esc_interrupt)
            # Wait for this specific task to complete before accepting next input
            try:
                await components.executor.wait_for(wait_id)
            finally:
                # Stop ESC monitor and wait for it to finish cleaning up TTY
                stop_event.set()
                with contextlib.suppress(Exception):
                    await esc_task

    except KeyboardInterrupt:
        await _handle_keyboard_interrupt(components.executor)
        exit_hint_printed = True
    finally:
        # Restore original SIGINT handler
        with contextlib.suppress(Exception):
            restore_sigint()
        await cleanup_app_components(components)

        if not exit_hint_printed:
            active_session_id = components.executor.context.current_session_id()
            if active_session_id and Session.exists(active_session_id):
                log(f"Session ID: {active_session_id}")
                log(f"Resume with: klaude --resume-by-id {active_session_id}")
