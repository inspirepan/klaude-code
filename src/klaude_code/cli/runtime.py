import asyncio
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import typer
from rich.text import Text

from klaude_code import ui
from klaude_code.command import is_interactive_command
from klaude_code.config import Config, load_config
from klaude_code.core.agent import DefaultModelProfileProvider, VanillaModelProfileProvider
from klaude_code.core.executor import Executor
from klaude_code.core.sub_agent import iter_sub_agent_profiles
from klaude_code.core.tool import SkillLoader, SkillTool
from klaude_code.llm import LLMClients
from klaude_code.protocol import events, op
from klaude_code.protocol.model import UserInputPayload
from klaude_code.trace import DebugType, log, set_debug_logging
from klaude_code.ui.modes.repl import build_repl_status_snapshot
from klaude_code.ui.modes.repl.input_prompt_toolkit import REPLStatusSnapshot
from klaude_code.ui.terminal.color import is_light_terminal_background
from klaude_code.ui.terminal.control import install_sigint_double_press_exit, start_esc_interrupt_monitor
from klaude_code.ui.terminal.progress_bar import OSC94States, emit_osc94
from klaude_code.version import get_update_message


class PrintCapable(Protocol):
    """Protocol for objects that can print styled content."""

    def print(self, *objects: Any, style: Any | None = None, end: str = "\n") -> None: ...


DEBUG_FILTER_HELP = "Comma-separated debug types: " + ", ".join(dt.value for dt in DebugType)


def _parse_debug_filters(raw: str | None) -> set[DebugType] | None:
    if raw is None:
        return None
    filters: set[DebugType] = set()
    for chunk in raw.split(","):
        normalized = chunk.strip().lower().replace("-", "_")
        if not normalized:
            continue
        try:
            filters.add(DebugType(normalized))
        except ValueError:  # pragma: no cover - user input validation
            valid_options = ", ".join(dt.value for dt in DebugType)
            log(
                (
                    f"Invalid debug filter '{normalized}'. Valid options: {valid_options}",
                    "red",
                )
            )
            raise typer.Exit(2) from None
    return filters or None


def resolve_debug_settings(flag: bool, raw_filters: str | None) -> tuple[bool, set[DebugType] | None]:
    filters = _parse_debug_filters(raw_filters)
    effective_flag = flag or (filters is not None)
    return effective_flag, filters


@dataclass
class AppInitConfig:
    """Configuration for initializing the application components."""

    model: str | None
    debug: bool
    vanilla: bool
    is_exec_mode: bool = False
    debug_filters: set[DebugType] | None = None


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


async def initialize_app_components(init_config: AppInitConfig) -> AppComponents:
    """Initialize all application components (LLM clients, executor, UI)."""
    set_debug_logging(init_config.debug, filters=init_config.debug_filters)

    config = load_config()
    if config is None:
        raise typer.Exit(1)

    # Initialize skills
    skill_loader = SkillLoader()
    skill_loader.discover_skills()
    SkillTool.set_skill_loader(skill_loader)

    # Initialize LLM clients
    try:
        enabled_sub_agents = [p.name for p in iter_sub_agent_profiles()]
        llm_clients = LLMClients.from_config(
            config,
            model_override=init_config.model,
            enabled_sub_agents=enabled_sub_agents,
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
    )

    # Start executor in background
    executor_task = asyncio.create_task(executor.start())

    theme: str | None = config.theme
    if theme is None:
        # Auto-detect theme from terminal background when config does not specify a theme.
        detected = is_light_terminal_background()
        if detected is True:
            theme = "light"
        elif detected is False:
            theme = "dark"

    # Set up UI components using factory functions
    display: ui.DisplayABC
    if init_config.is_exec_mode:
        display = ui.create_exec_display(debug=init_config.debug)
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


async def cleanup_app_components(components: AppComponents) -> None:
    """Clean up all application components."""
    try:
        # Clean shutdown
        await components.executor.stop()
        components.executor_task.cancel()

        # Signal UI to stop
        await components.event_queue.put(events.EndEvent())
        await components.display_task
    finally:
        # Always attempt to clear Ghostty progress bar and restore cursor visibility
        try:
            emit_osc94(OSC94States.HIDDEN)
        except Exception:
            # Best-effort only; never fail cleanup due to OSC errors
            pass

        try:
            # Ensure the terminal cursor is visible even if Rich's Status spinner
            # did not get a chance to stop cleanly (e.g. on KeyboardInterrupt).
            stream = getattr(sys, "__stdout__", None) or sys.stdout
            stream.write("\033[?25h")
            stream.flush()
        except Exception:
            # If this fails the shell can still recover via `reset`/`stty sane`.
            pass


async def _handle_keyboard_interrupt(executor: Executor) -> None:
    """Handle Ctrl+C by logging and sending a global interrupt."""

    log("Bye!")
    try:
        await executor.submit(op.InterruptOperation(target_session_id=None))
    except Exception:
        # Executor might already be stopping
        pass


async def run_exec(init_config: AppInitConfig, input_content: str) -> None:
    """Run a single command non-interactively using the provided configuration."""

    components = await initialize_app_components(init_config)

    try:
        # Generate a new session ID for exec mode
        session_id = uuid.uuid4().hex

        # Init Agent
        await components.executor.submit_and_wait(op.InitAgentOperation(session_id=session_id))
        await components.event_queue.join()

        # Submit the input content directly
        await components.executor.submit_and_wait(
            op.UserInputOperation(input=UserInputPayload(text=input_content), session_id=session_id)
        )

    except KeyboardInterrupt:
        await _handle_keyboard_interrupt(components.executor)
    finally:
        await cleanup_app_components(components)


async def run_interactive(init_config: AppInitConfig, session_id: str | None = None) -> None:
    """Run the interactive REPL using the provided configuration."""

    components = await initialize_app_components(init_config)

    # No theme persistence from CLI anymore; config.theme controls theme when set.

    # Create status provider for bottom toolbar
    def _status_provider() -> REPLStatusSnapshot:
        agent = None
        if session_id and session_id in components.executor.context.active_agents:
            agent = components.executor.context.active_agents[session_id]

        # Check for updates (returns None if uv not available)
        update_message = get_update_message()

        return build_repl_status_snapshot(agent=agent, update_message=update_message)

    # Set up input provider for interactive mode
    input_provider: ui.InputProviderABC = ui.PromptToolkitInput(status_provider=_status_provider)

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
            elif isinstance(components.display, ui.DebugEventDisplay) and components.display.wrapped_display:
                if isinstance(components.display.wrapped_display, ui.REPLDisplay):
                    printer = components.display.wrapped_display.renderer

            if printer is not None:
                printer.print(Text(f" {MSG} ", style="bold yellow reverse"))
            else:
                print(MSG, file=sys.stderr)
        except Exception:
            # Fallback if themed print is unavailable
            print(MSG, file=sys.stderr)

    def _hide_progress() -> None:
        try:
            emit_osc94(OSC94States.HIDDEN)
        except Exception:
            pass

    restore_sigint = install_sigint_double_press_exit(_show_toast_once, _hide_progress)

    try:
        # Init Agent
        await components.executor.submit_and_wait(op.InitAgentOperation(session_id=session_id))
        await components.event_queue.join()
        # Input
        await input_provider.start()
        async for user_input in input_provider.iter_inputs():
            # Handle special commands
            if user_input.text.strip().lower() in {"exit", ":q", "quit"}:
                break
            elif user_input.text.strip() == "":
                continue
            # Submit user input operation - directly use the payload from iter_inputs
            submission_id = await components.executor.submit(
                op.UserInputOperation(input=user_input, session_id=session_id)
            )
            # If it's an interactive command (e.g., /model), avoid starting the ESC monitor
            # to prevent TTY conflicts with interactive prompts (questionary/prompt_toolkit).
            if is_interactive_command(user_input.text):
                await components.executor.wait_for(submission_id)
            else:
                # Esc monitor for long-running, interruptible operations
                async def _on_esc_interrupt() -> None:
                    await components.executor.submit(op.InterruptOperation(target_session_id=session_id))

                stop_event, esc_task = start_esc_interrupt_monitor(_on_esc_interrupt)
                # Wait for this specific task to complete before accepting next input
                try:
                    await components.executor.wait_for(submission_id)
                finally:
                    # Stop ESC monitor and wait for it to finish cleaning up TTY
                    stop_event.set()
                    try:
                        await esc_task
                    except Exception:
                        pass

    except KeyboardInterrupt:
        await _handle_keyboard_interrupt(components.executor)
    finally:
        try:
            # Restore original SIGINT handler
            restore_sigint()
        except Exception:
            pass
        await cleanup_app_components(components)
