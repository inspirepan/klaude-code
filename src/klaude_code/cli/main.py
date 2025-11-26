import asyncio
import os
import select
import signal
import subprocess
import sys
import termios
import threading
import time
import tty
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import typer
from rich.style import StyleType
from rich.text import Text

from importlib.metadata import version as pkg_version

from klaude_code import ui
from klaude_code.command.registry import is_interactive_command
from klaude_code.config import config_path, load_config
from klaude_code.config.config import Config
from klaude_code.config.list_model import display_models_and_providers
from klaude_code.config.select_model import select_model_from_config
from klaude_code.core.agent import AgentLLMClients, DefaultModelProfileProvider, VanillaModelProfileProvider
from klaude_code.core.executor import Executor
from klaude_code.core.sub_agent import iter_sub_agent_profiles
from klaude_code.core.tool.skill_loader import SkillLoader
from klaude_code.core.tool.skill_tool import SkillTool
from klaude_code.llm import LLMClientABC, create_llm_client
from klaude_code.protocol import op
from klaude_code.protocol.events import EndEvent, Event
from klaude_code.protocol.llm_parameter import LLMConfigParameter
from klaude_code.protocol.model import ResponseMetadataItem
from klaude_code.session import Session, resume_select_session
from klaude_code.trace import DebugType, log, log_debug, set_debug_logging
from klaude_code.ui.base.progress_bar import OSC94States, emit_osc94
from klaude_code.ui.base.terminal_color import is_light_terminal_background
from klaude_code.ui.repl.input import REPLStatusSnapshot
from klaude_code.version import get_update_message


def set_terminal_title(title: str) -> None:
    """Set terminal window title using ANSI escape sequence."""
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()


class PrintCapable(Protocol):
    """Protocol for objects that can print styled content."""

    def print(self, *objects: Any, style: StyleType | None = None, end: str = "\n") -> None: ...


def start_esc_interrupt_monitor(
    executor: Executor, session_id: str | None
) -> tuple[threading.Event, asyncio.Task[None]]:
    """Start ESC monitoring thread: Detect pure ESC keypress, print `esc` once and submit interrupt operation.
    Returns (stop_event, esc_task).
    """
    stop_event = threading.Event()
    loop = asyncio.get_running_loop()

    def _esc_monitor(stop: threading.Event) -> None:
        try:
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
        except Exception as e:
            log((f"esc monitor init error: {e}", "r red"))
            return
        try:
            tty.setcbreak(fd)
            while not stop.is_set():
                r, _, _ = select.select([sys.stdin], [], [], 0.05)
                if not r:
                    continue
                try:
                    ch = os.read(fd, 1).decode(errors="ignore")
                except Exception:
                    continue
                if ch == "\x1b":
                    seq = ""
                    r2, _, _ = select.select([sys.stdin], [], [], 0.005)
                    while r2:
                        try:
                            seq += os.read(fd, 1).decode(errors="ignore")
                        except Exception:
                            break
                        r2, _, _ = select.select([sys.stdin], [], [], 0.0)
                    if seq == "":
                        try:
                            asyncio.run_coroutine_threadsafe(
                                executor.submit(op.InterruptOperation(target_session_id=session_id)),
                                loop,
                            )
                        except Exception:
                            pass
                        stop.set()
        except Exception as e:
            log((f"esc monitor error: {e}", "r red"))
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except Exception:
                pass

    esc_task: asyncio.Task[None] = asyncio.create_task(asyncio.to_thread(_esc_monitor, stop_event))
    return stop_event, esc_task


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
            log((f"Invalid debug filter '{normalized}'. Valid options: {valid_options}", "red"))
            raise typer.Exit(2) from None
    return filters or None


def _resolve_debug_settings(flag: bool, raw_filters: str | None) -> tuple[bool, set[DebugType] | None]:
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
    llm_clients: AgentLLMClients
    llm_config: LLMConfigParameter
    executor: Executor
    executor_task: asyncio.Task[None]
    event_queue: asyncio.Queue[Event]
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
    skills = skill_loader.discover_skills()
    if skills:
        user_count = sum(1 for s in skills if s.location == "user")
        project_count = sum(1 for s in skills if s.location == "project")
        parts: list[str] = []
        if user_count > 0:
            parts.append(f"{user_count} user")
        if project_count > 0:
            parts.append(f"{project_count} project")
        log_debug(f"Discovered {len(skills)} Claude Skills ({', '.join(parts)})")
    SkillTool.set_skill_loader(skill_loader)
    # Resolve main agent LLM config
    try:
        llm_config = config.get_model_config(init_config.model) if init_config.model else config.get_main_model_config()
    except ValueError as exc:
        if init_config.model:
            log((f"Error: model '{init_config.model}' is not defined in the config", "red"))
            log(("Hint: run `klaude list` to view available models", "yellow"))
        else:
            log((f"Error: failed to load the default model configuration: {exc}", "red"))
        raise typer.Exit(2) from None
    llm_client: LLMClientABC = create_llm_client(llm_config)
    log_debug(
        "Main model config",
        llm_config.model_dump_json(exclude_none=True),
        style="yellow",
        debug_type=DebugType.LLM_CONFIG,
    )

    llm_clients = AgentLLMClients(main=llm_client)
    model_profile_provider = VanillaModelProfileProvider() if init_config.vanilla else DefaultModelProfileProvider()

    for profile in iter_sub_agent_profiles():
        model_name = config.subagent_models.get(profile.name)
        if not model_name:
            continue
        if not profile.enabled_for_model(llm_client.model_name):
            continue
        sub_llm_config = config.get_model_config(model_name)
        sub_llm_client = create_llm_client(sub_llm_config)
        llm_clients.set_sub_agent_client(profile.name, sub_llm_client)
        log_debug(
            f"Sub-agent {profile.name} model config",
            sub_llm_config.model_dump_json(exclude_none=True),
            style="yellow",
            debug_type=DebugType.LLM_CONFIG,
        )

    # Create event queue for communication between executor and UI
    event_queue: asyncio.Queue[Event] = asyncio.Queue()

    # Create executor with the LLM client
    executor = Executor(
        event_queue,
        llm_clients,
        llm_config,
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

    # Set up UI components
    display: ui.DisplayABC
    if init_config.is_exec_mode:
        # Use ExecDisplay for exec mode - only shows task results
        display = ui.ExecDisplay()
    else:
        # Use REPLDisplay for interactive mode
        repl_display = ui.REPLDisplay(theme=theme)
        display = repl_display if not init_config.debug else ui.DebugEventDisplay(repl_display)

    # Start UI display task
    display_task = asyncio.create_task(display.consume_event_loop(event_queue))

    return AppComponents(
        config=config,
        llm_clients=llm_clients,
        llm_config=llm_config,
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
        await components.event_queue.put(EndEvent())
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


async def run_exec(init_config: AppInitConfig, input_content: str) -> None:
    """Run a single command non-interactively using the provided configuration."""

    components = await initialize_app_components(init_config)

    try:
        # Generate a new session ID for exec mode
        session_id = uuid.uuid4().hex

        # Init Agent
        init_id = await components.executor.submit(op.InitAgentOperation(session_id=session_id))
        await components.executor.wait_for_completion(init_id)
        await components.event_queue.join()

        # Submit the input content directly
        submission_id = await components.executor.submit(
            op.UserInputOperation(content=input_content, session_id=session_id)
        )
        await components.executor.wait_for_completion(submission_id)

    except KeyboardInterrupt:
        log("Bye!")
        # Send interrupt to stop any running tasks
        try:
            await components.executor.submit(op.InterruptOperation(target_session_id=None))
        except:  # noqa: E722
            pass  # Executor might already be stopping
    finally:
        await cleanup_app_components(components)


async def run_interactive(init_config: AppInitConfig, session_id: str | None = None) -> None:
    """Run the interactive REPL using the provided configuration."""

    components = await initialize_app_components(init_config)

    # No theme persistence from CLI anymore; config.theme controls theme when set.

    # Create status provider for bottom toolbar
    def _status_provider() -> REPLStatusSnapshot:
        # Get model name from active agent or fallback to main LLM client
        model_name = "N/A"
        context_usage_percent: float | None = None
        llm_calls = 0
        tool_calls = 0

        if session_id and session_id in components.executor.context.active_agents:
            agent = components.executor.context.active_agents[session_id]
            model_name = agent.session.model_name or components.llm_clients.main.model_name

            # Count AssistantMessageItem and ToolCallItem in conversation history
            from klaude_code.protocol.model import AssistantMessageItem, ToolCallItem

            for item in agent.session.conversation_history:
                if isinstance(item, AssistantMessageItem):
                    llm_calls += 1
                elif isinstance(item, ToolCallItem):
                    tool_calls += 1

            # Find the most recent ResponseMetadataItem in conversation history
            for item in reversed(agent.session.conversation_history):
                if isinstance(item, ResponseMetadataItem):
                    usage = item.usage
                    if usage and hasattr(usage, "context_usage_percent"):
                        context_usage_percent = usage.context_usage_percent
                    break
        else:
            # Fallback to main LLM client model name if no agent exists yet
            model_name = components.llm_clients.main.model_name

        # Check for updates (returns None if uv not available)
        update_message = get_update_message()

        return REPLStatusSnapshot(
            model_name=model_name,
            context_usage_percent=context_usage_percent,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            update_message=update_message,
        )

    # Set up input provider for interactive mode
    input_provider: ui.InputProviderABC = ui.PromptToolkitInput(status_provider=_status_provider)

    # --- Custom Ctrl+C handler: double-press within 2s to exit, single press shows toast ---
    last_sigint_time: float = 0.0
    original_sigint = signal.getsignal(signal.SIGINT)

    def _show_toast_once() -> None:
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
                printer.print(Text(" Press ctrl+c again to exit ", style="bold yellow reverse"))
            else:
                print("Press ctrl+c again to exit", file=sys.stderr)
        except Exception:
            # Fallback if themed print is unavailable
            print("Press ctrl+c again to exit", file=sys.stderr)

    def _sigint_handler(signum, frame):  # type: ignore[no-untyped-def]
        nonlocal last_sigint_time
        now = time.monotonic()
        if now - last_sigint_time <= 2:
            # Second press within window: exit by raising KeyboardInterrupt
            emit_osc94(OSC94States.HIDDEN)
            raise KeyboardInterrupt
        # First press: remember and show toast
        last_sigint_time = now
        _show_toast_once()

    signal.signal(signal.SIGINT, _sigint_handler)  # type: ignore[assignment]

    try:
        # Init Agent
        init_id = await components.executor.submit(op.InitAgentOperation(session_id=session_id))
        await components.executor.wait_for_completion(init_id)
        await components.event_queue.join()
        # Input
        await input_provider.start()
        async for user_input in input_provider.iter_inputs():
            # Handle special commands
            if user_input.strip().lower() in {"exit", ":q", "quit"}:
                break
            elif user_input.strip() == "":
                continue
            # Submit user input operation
            submission_id = await components.executor.submit(
                op.UserInputOperation(content=user_input, session_id=session_id)
            )
            # If it's an interactive command (e.g., /model), avoid starting the ESC monitor
            # to prevent TTY conflicts with interactive prompts (questionary/prompt_toolkit).
            if is_interactive_command(user_input):
                await components.executor.wait_for_completion(submission_id)
            else:
                # Esc monitor for long-running, interruptible operations
                stop_event, esc_task = start_esc_interrupt_monitor(components.executor, session_id)
                # Wait for this specific task to complete before accepting next input
                try:
                    await components.executor.wait_for_completion(submission_id)
                finally:
                    # Stop ESC monitor and wait for it to finish cleaning up TTY
                    stop_event.set()
                    try:
                        await esc_task
                    except Exception:
                        pass

    except KeyboardInterrupt:
        log("Bye!")
        # Send interrupt to stop any running tasks
        try:
            await components.executor.submit(op.InterruptOperation(target_session_id=None))
        except:  # noqa: E722
            pass  # Executor might already be stopping
    finally:
        try:
            # Restore original SIGINT handler
            signal.signal(signal.SIGINT, original_sigint)
        except Exception:
            pass
        await cleanup_app_components(components)


def _version_callback(value: bool) -> None:
    """Show version and exit."""
    if value:
        try:
            ver = pkg_version("klaude-code")
        except Exception:
            ver = "unknown"
        print(f"klaude-code {ver}")
        raise typer.Exit(0)


app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    no_args_is_help=False,
)


@app.command("list")
def list_models():
    """List all models and providers configuration"""
    config = load_config()
    if config is None:
        raise typer.Exit(1)
    display_models_and_providers(config)


@app.command("config")
def edit_config():
    """Open the configuration file in $EDITOR or default system editor"""
    editor = os.environ.get("EDITOR")

    # If no EDITOR is set, prioritize TextEdit on macOS
    if not editor:
        # Try common editors in order of preference on other platforms
        for cmd in [
            "code",
            "nvim",
            "vim",
            "nano",
        ]:
            try:
                subprocess.run(["which", cmd], check=True, capture_output=True)
                editor = cmd
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue

    # If no editor found, try platform-specific defaults
    if not editor:
        if sys.platform == "darwin":  # macOS
            editor = "open"
        elif sys.platform == "win32":  # Windows
            editor = "notepad"
        else:  # Linux and other Unix systems
            editor = "xdg-open"

    # Ensure config file exists
    config = load_config()
    if config is None:
        raise typer.Exit(1)

    try:
        if editor == "open -a TextEdit":
            subprocess.run(["open", "-a", "TextEdit", str(config_path)], check=True)
        elif editor in ["open", "xdg-open"]:
            # For open/xdg-open, we need to pass the file directly
            subprocess.run([editor, str(config_path)], check=True)
        else:
            subprocess.run([editor, str(config_path)], check=True)
    except subprocess.CalledProcessError as e:
        log((f"Error: Failed to open editor: {e}", "red"))
        raise typer.Exit(1)
    except FileNotFoundError:
        log((f"Error: Editor '{editor}' not found", "red"))
        log("Please install a text editor or set your $EDITOR environment variable")
        raise typer.Exit(1)


@app.command("exec")
def exec_command(
    input_content: str = typer.Argument("", help="Input message to execute"),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Override model config name (uses main model by default)",
        rich_help_panel="LLM",
    ),
    select_model: bool = typer.Option(
        False,
        "--select-model",
        "-s",
        help="Interactively choose a model at startup",
        rich_help_panel="LLM",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        "-d",
        help="Enable debug mode",
        rich_help_panel="Debug",
    ),
    debug_filter: str | None = typer.Option(
        None,
        "--debug-filter",
        help=DEBUG_FILTER_HELP,
        rich_help_panel="Debug",
    ),
    vanilla: bool = typer.Option(
        False,
        "--vanilla",
        help="Vanilla mode exposes the model's raw API behavior: it provides only minimal tools (Bash, Read & Edit) and omits system prompts and reminders.",
    ),
):
    """Execute non-interactively with provided input."""

    # Set terminal title with current folder name
    folder_name = os.path.basename(os.getcwd())
    set_terminal_title(f"{folder_name}: klaude")

    parts: list[str] = []

    # Handle stdin input
    if not sys.stdin.isatty():
        try:
            stdin = sys.stdin.read().rstrip("\n")
            if stdin:
                parts.append(stdin)
        except Exception as e:
            log((f"Error reading from stdin: {e}", "red"))

    if input_content:
        parts.append(input_content)

    input_content = "\n".join(parts)
    if len(input_content) == 0:
        log(("Error: No input content provided", "red"))
        raise typer.Exit(1)

    chosen_model = model
    if select_model:
        # Prefer the explicitly provided model as default; otherwise main model
        config = load_config()
        if config is None:
            raise typer.Exit(1)
        default_name = model or config.main_model
        chosen_model = select_model_from_config(preferred=default_name)
        if chosen_model is None:
            return

    debug_enabled, debug_filters = _resolve_debug_settings(debug, debug_filter)

    init_config = AppInitConfig(
        model=chosen_model,
        debug=debug_enabled,
        vanilla=vanilla,
        is_exec_mode=True,
        debug_filters=debug_filters,
    )

    asyncio.run(
        run_exec(
            init_config=init_config,
            input_content=input_content,
        )
    )


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Override model config name (uses main model by default)",
        rich_help_panel="LLM",
    ),
    continue_: bool = typer.Option(False, "--continue", "-c", help="Continue from latest session"),
    resume: bool = typer.Option(False, "--resume", "-r", help="Select a session to resume for this project"),
    select_model: bool = typer.Option(
        False,
        "--select-model",
        "-s",
        help="Interactively choose a model at startup",
        rich_help_panel="LLM",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        "-d",
        help="Enable debug mode",
        rich_help_panel="Debug",
    ),
    debug_filter: str | None = typer.Option(
        None,
        "--debug-filter",
        help=DEBUG_FILTER_HELP,
        rich_help_panel="Debug",
    ),
    vanilla: bool = typer.Option(
        False,
        "--vanilla",
        help="Vanilla mode exposes the model's raw API behavior: it provides only minimal tools (Bash, Read & Edit) and omits system prompts and reminders.",
    ),
):
    # Only run interactive mode when no subcommand is invoked
    if ctx.invoked_subcommand is None:
        # Set terminal title with current folder name
        folder_name = os.path.basename(os.getcwd())
        set_terminal_title(f"{folder_name}: klaude")
        # Interactive mode
        chosen_model = model
        if select_model:
            chosen_model = select_model_from_config(preferred=model)
            if chosen_model is None:
                return

        # Resolve session id before entering asyncio loop
        session_id: str | None = None
        if resume:
            session_id = resume_select_session()
            if session_id is None:
                return
        # If user didn't pick, allow fallback to --continue
        if session_id is None and continue_:
            session_id = Session.most_recent_session_id()
        # If still no session_id, generate a new one for a new session
        if session_id is None:
            session_id = uuid.uuid4().hex

        debug_enabled, debug_filters = _resolve_debug_settings(debug, debug_filter)

        init_config = AppInitConfig(
            model=chosen_model,
            debug=debug_enabled,
            vanilla=vanilla,
            debug_filters=debug_filters,
        )

        asyncio.run(
            run_interactive(
                init_config=init_config,
                session_id=session_id,
            )
        )
