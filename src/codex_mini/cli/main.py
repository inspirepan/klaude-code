import asyncio
import json
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

from codex_mini import ui
from codex_mini.command.registry import is_interactive_command
from codex_mini.config import config_path, load_config
from codex_mini.config.config import Config
from codex_mini.config.list_model import display_models_and_providers
from codex_mini.config.select_model import select_model_from_config
from codex_mini.core.agent import AgentLLMClients
from codex_mini.core.executor import Executor
from codex_mini.core.tool.tool_context import set_unrestricted_mode
from codex_mini.llm import LLMClientABC, create_llm_client
from codex_mini.protocol import op
from codex_mini.protocol.events import EndEvent, Event
from codex_mini.protocol.llm_parameter import LLMConfigParameter
from codex_mini.session import Session, resume_select_session
from codex_mini.trace import log, log_debug


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


@dataclass
class UIArgs:
    theme: str | None
    light: bool | None
    dark: bool | None


@dataclass
class AppInitConfig:
    """Configuration for initializing the application components."""

    model: str | None
    # If provided, this overrides main agent's model configuration
    llm_config_override: LLMConfigParameter | None
    debug: bool
    ui_args: UIArgs | None
    unrestricted: bool
    vanilla: bool
    is_exec_mode: bool = False


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
    # Set read limits policy
    set_unrestricted_mode(init_config.unrestricted)

    config = load_config()
    # Resolve main agent LLM config with override support
    if init_config.llm_config_override is not None:
        llm_config = init_config.llm_config_override
    else:
        try:
            llm_config = (
                config.get_model_config(init_config.model) if init_config.model else config.get_main_model_config()
            )
        except ValueError as exc:
            if init_config.model:
                log((f"Error: model '{init_config.model}' is not defined in the config", "red"))
                log(("Hint: run `cdx list` to view available models", "yellow"))
            else:
                log((f"Error: failed to load the default model configuration: {exc}", "red"))
            raise typer.Exit(2) from None
    llm_client: LLMClientABC = create_llm_client(llm_config)
    if init_config.debug:
        log_debug("▷▷▷ llm [Model Config]", llm_config.model_dump_json(exclude_none=True), style="yellow")
        llm_client.enable_debug_mode()

    llm_clients = AgentLLMClients(main=llm_client)

    if config.task_model:
        task_llm_config = config.get_model_config(config.task_model)
        task_llm_client = create_llm_client(task_llm_config)
        llm_clients.task = task_llm_client
        if init_config.debug:
            log_debug("▷▷▷ llm [Task Model Config]", task_llm_config.model_dump_json(exclude_none=True), style="yellow")
            task_llm_client.enable_debug_mode()

    if config.oracle_model:
        oracle_llm_config = config.get_model_config(config.oracle_model)
        oracle_llm_client = create_llm_client(oracle_llm_config)
        llm_clients.oracle = oracle_llm_client
        if init_config.debug:
            log_debug(
                "▷▷▷ llm [Oracle Model Config]", oracle_llm_config.model_dump_json(exclude_none=True), style="yellow"
            )
            oracle_llm_client.enable_debug_mode()

    # Create event queue for communication between executor and UI
    event_queue: asyncio.Queue[Event] = asyncio.Queue()

    # Create executor with the LLM client
    executor = Executor(event_queue, llm_clients, llm_config, debug_mode=init_config.debug, vanilla=init_config.vanilla)

    # Start executor in background
    executor_task = asyncio.create_task(executor.start())

    theme: str | None = config.theme
    if init_config.ui_args:
        if init_config.ui_args.theme:
            theme = init_config.ui_args.theme
        elif init_config.ui_args.light:
            theme = "light"
        elif init_config.ui_args.dark:
            theme = "dark"

    # Set up UI components
    display: ui.DisplayABC
    if init_config.is_exec_mode:
        # Use ExecDisplay for exec mode - only shows task results
        display = ui.ExecDisplay()
    else:
        # Use REPLDisplay for interactive mode
        repl_display = ui.REPLDisplay(theme=theme)
        display = repl_display if not init_config.debug else ui.DebugEventDisplay(repl_display, write_to_file=True)

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
    # Clean shutdown
    await components.executor.stop()
    components.executor_task.cancel()

    # Signal UI to stop
    await components.event_queue.put(EndEvent())
    await components.display_task


def parse_llm_config_override(model_config_json: str | None, debug: bool) -> LLMConfigParameter | None:
    """Parse LLMConfigParameter from JSON string.

    Returns None when no JSON provided. Exits with code 2 on validation error.
    """
    if not model_config_json:
        return None
    try:
        cfg = LLMConfigParameter.model_validate_json(model_config_json)
        if debug:
            pretty = json.dumps(json.loads(model_config_json), ensure_ascii=False)
            log_debug("▷▷▷ cli [Model Config JSON Override]", pretty, style="yellow")
        return cfg
    except Exception as e:
        log((f"Invalid --model-config-json: {e}", "red"))
        raise typer.Exit(2)


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

    # Special handling for interactive mode theme saving
    if init_config.ui_args and init_config.ui_args.theme:
        old_theme = components.config.theme
        components.config.theme = components.theme
        if old_theme != components.theme:
            await components.config.save()

    # Set up input provider for interactive mode
    input_provider: ui.InputProviderABC = ui.PromptToolkitInput()

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


app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    no_args_is_help=False,
)


@app.command("list")
def list_models():
    """List all models and providers configuration"""
    config = load_config()
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
    load_config()

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
    model_config_json: str | None = typer.Option(
        None,
        "--model-config-json",
        help=(
            "Override main agent model config using a JSON string of LLMConfigParameter. "
            "Takes precedence over --model. Also reads CODEX_MODEL_CONFIG_JSON. "
            'Example: {"protocol":"responses","api_key":"sk-...",'
            '"base_url":"https://api.openai.com/v1","model":"gpt-5"}'
        ),
        envvar="CODEX_MODEL_CONFIG_JSON",
        rich_help_panel="LLM",
    ),
    select_model: bool = typer.Option(
        False,
        "--select-model",
        "-s",
        help="Interactively choose a model at startup",
        rich_help_panel="LLM",
    ),
    set_theme: str | None = typer.Option(
        None,
        "--set-theme",
        help="Set UI theme (light or dark)",
        rich_help_panel="Theme",
    ),
    light: bool = typer.Option(False, "--light", help="Use light theme", rich_help_panel="Theme"),
    dark: bool = typer.Option(False, "--dark", help="Use dark theme", rich_help_panel="Theme"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
    unrestricted: bool = typer.Option(
        False,
        "--unrestricted",
        "-u",
        help="Disable safety guardrails for file reads and shell command validation (use with caution)",
    ),
    vanilla: bool = typer.Option(False, "--vanilla", help="Use vanilla model with no system prompt and reminders"),
):
    """Execute non-interactively with provided input."""

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

    # Parse model-config override if provided
    llm_config_override: LLMConfigParameter | None = parse_llm_config_override(model_config_json, debug)

    chosen_model = model if llm_config_override is None else None
    if select_model and llm_config_override is None:
        # Prefer the explicitly provided model as default; otherwise main model
        default_name = model or load_config().main_model
        chosen_model = select_model_from_config(preferred=default_name)
        if chosen_model is None:
            return
    elif select_model and llm_config_override is not None:
        log(("--select-model ignored due to --model-config-json override", "yellow"))

    init_config = AppInitConfig(
        model=chosen_model,
        llm_config_override=llm_config_override,
        debug=debug,
        ui_args=UIArgs(theme=set_theme, light=light, dark=dark),
        unrestricted=unrestricted,
        vanilla=vanilla,
        is_exec_mode=True,
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
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Override model config name (uses main model by default)",
        rich_help_panel="LLM",
    ),
    model_config_json: str | None = typer.Option(
        None,
        "--model-config-json",
        help=(
            "Override main agent model config using a JSON string of LLMConfigParameter. "
            "Takes precedence over --model. "
        ),
        envvar="CODEX_MODEL_CONFIG_JSON",
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
    set_theme: str | None = typer.Option(
        None,
        "--set-theme",
        help="Set UI theme (light or dark)",
        rich_help_panel="Theme",
    ),
    light: bool = typer.Option(False, "--light", help="Use light theme", rich_help_panel="Theme"),
    dark: bool = typer.Option(False, "--dark", help="Use dark theme", rich_help_panel="Theme"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
    unrestricted: bool = typer.Option(
        False,
        "--unrestricted",
        "-u",
        help="Disable safety guardrails for file reads and shell command validation (use with caution)",
    ),
    vanilla: bool = typer.Option(False, "--vanilla", help="Use vanilla model with no system prompt and reminders"),
):
    """Codex CLI Minimal"""
    # Only run interactive mode when no subcommand is invoked
    if ctx.invoked_subcommand is None:
        # Interactive mode
        # Parse model-config override if provided
        llm_config_override: LLMConfigParameter | None = parse_llm_config_override(model_config_json, debug)

        chosen_model = model if llm_config_override is None else None
        if select_model and llm_config_override is None:
            # Prefer the explicitly provided model as default; otherwise main model
            default_name = model or load_config().main_model
            chosen_model = select_model_from_config(preferred=default_name)
            if chosen_model is None:
                return
        elif select_model and llm_config_override is not None:
            log(("--select-model ignored due to --model-config-json override", "yellow"))

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

        init_config = AppInitConfig(
            model=chosen_model,
            llm_config_override=llm_config_override,
            debug=debug,
            ui_args=UIArgs(theme=set_theme, light=light, dark=dark),
            unrestricted=unrestricted,
            vanilla=vanilla,
        )

        asyncio.run(
            run_interactive(
                init_config=init_config,
                session_id=session_id,
            )
        )
