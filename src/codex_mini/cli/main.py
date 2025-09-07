import asyncio
import os
import select
import sys
import termios
import threading
import tty

import typer

from codex_mini import ui
from codex_mini.config import load_config
from codex_mini.config.list_model import display_models_and_providers
from codex_mini.core.executor import Executor
from codex_mini.llm import LLMClientABC, create_llm_client
from codex_mini.protocol.events import EndEvent, Event
from codex_mini.session import Session
from codex_mini.trace import log, log_debug


def _select_model_from_config(preferred: str | None = None) -> str | None:
    """
    Interactive single-choice model selector.
    for `--select-model`
    """
    config = load_config()
    models = config.model_list

    if not models:
        raise ValueError("No models configured. Please update your config.yaml")

    names: list[str] = [m.model_name for m in models]
    default_name: str | None = (
        preferred if preferred in names else (config.main_model if config.main_model in names else None)
    )

    try:
        import questionary

        choices: list[questionary.Choice] = []

        max_model_name_length = max(len(m.model_name) for m in models)
        for m in models:
            star = "★ " if m.model_name == config.main_model else "  "
            label = [
                ("class:t", f"{star}{m.model_name:<{max_model_name_length}}   → "),
                ("class:b", m.model_params.model or "N/A"),
                ("class:d", f" {m.provider}"),
            ]
            choices.append(questionary.Choice(title=label, value=m.model_name))

        result = questionary.select(
            message="Select a model:",
            choices=choices,
            default=default_name,
            pointer="→",
            instruction="↑↓ to move • Enter to select",
            style=questionary.Style(
                [
                    ("t", ""),
                    ("b", "bold"),
                    ("d", "dim"),
                ]
            ),
        ).ask()
        if isinstance(result, str) and result in names:
            return result
    except Exception as e:
        log_debug(f"Failed to use questionary, falling back to default model, {e}")
        pass


def _resume_select_session() -> str | None:
    """
    List sessions for current project and let user pick one.
    for `--resume`
    """
    sessions = Session.list()
    if not sessions:
        log("No sessions found for this project.")
        return None

    # Format timestamps
    import time as _t

    def _fmt(ts: float) -> str:
        try:
            return _t.strftime("%m-%d %H:%M:%S", _t.localtime(ts))
        except Exception:
            return str(ts)

    try:
        import questionary

        choices: list[questionary.Choice] = []
        for s in sessions:
            first_user_message = s.first_user_message or "N/A"
            msg_count_display = "N/A" if s.messages_count == -1 else str(s.messages_count)
            model_display = s.model_name or "N/A"

            title = [
                ("class:d", f"{_fmt(s.created_at):<16} "),
                ("class:d", f"{_fmt(s.updated_at):<16} "),
                ("class:b", f"{msg_count_display:>3}  "),
                ("class:t", f"{model_display[:14] + '…' if len(model_display) > 14 else model_display:<15} "),
                ("class:t", f"{first_user_message.strip().replace('\n', ' ↩ '):<50}"),
            ]
            choices.append(questionary.Choice(title=title, value=s.id))
        return questionary.select(
            message=f"{' Created at':<17} {'Updated at':<16} {'Msg':>3}  {'Model':<15} {'First message':<50}",
            choices=choices,
            pointer="→",
            instruction="↑↓ to move",
            style=questionary.Style(
                [
                    ("t", ""),
                    ("b", "bold"),
                    ("d", "dim"),
                ]
            ),
        ).ask()
    except Exception as e:
        log_debug(f"Failed to use questionary for session select, {e}")
        # Fallback: numbered prompt
        for i, s in enumerate(sessions, 1):
            msg_count_display = "N/A" if s.messages_count == -1 else str(s.messages_count)
            model_display = s.model_name or "N/A"
            print(
                f"{i}. {_fmt(s.updated_at)}  {msg_count_display:>3} {model_display[:14] + '…' if len(model_display) > 14 else model_display:<15} {s.id}  {s.work_dir}"
            )
        try:
            raw = input("Select a session number: ").strip()
            idx = int(raw)
            if 1 <= idx <= len(sessions):
                return str(sessions[idx - 1].id)
        except Exception:
            return None
    return None


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
                                executor.submit(
                                    {
                                        "type": "interrupt",
                                        "target_session_id": session_id,
                                    }
                                ),
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


async def run_interactive(
    model: str | None = None,
    debug: bool = False,
    session_id: str | None = None,
):
    """Run the interactive REPL using the new executor architecture."""
    config = load_config()
    llm_config = config.get_model_config(model) if model else config.get_main_model_config()

    if debug:
        log_debug("▷▷▷ llm [Model Config]", llm_config.model_dump_json(exclude_none=True), style="yellow")

    llm_client: LLMClientABC = create_llm_client(llm_config)
    if debug:
        llm_client.enable_debug_mode()

    # Create event queue for communication between executor and UI
    event_queue: asyncio.Queue[Event] = asyncio.Queue()

    # Create executor with the LLM client
    executor = Executor(event_queue, llm_client, llm_config, debug_mode=debug)

    # Start executor in background
    executor_task = asyncio.create_task(executor.start())

    # Set up UI components
    repl_display = ui.REPLDisplay()
    display: ui.DisplayABC = repl_display if not debug else ui.DebugEventDisplay(repl_display, write_to_file=True)
    input_provider: ui.InputProviderABC = ui.PromptToolkitInput()

    # Start UI display task
    display_task = asyncio.create_task(display.consume_event_loop(event_queue))

    try:
        # Init Agent
        init_id = await executor.submit({"type": "init_agent", "session_id": session_id})
        await executor.wait_for_completion(init_id)
        await event_queue.join()
        # Input
        await input_provider.start()
        async for user_input in input_provider.iter_inputs():
            # Handle special commands
            if user_input.strip().lower() in {"exit", ":q", "quit"}:
                break
            elif user_input.strip() == "":
                continue
            # Submit user input operation
            submission_id = await executor.submit(
                {
                    "type": "user_input",
                    "content": user_input,
                    "session_id": session_id,
                }
            )
            # Esc monitor
            stop_event, esc_task = start_esc_interrupt_monitor(executor, session_id)
            # Wait for this specific task to complete before accepting next input
            try:
                await executor.wait_for_completion(submission_id)
            finally:
                # Stop ESC monitor and wait for it to finish cleaning up TTY
                stop_event.set()
                try:
                    await esc_task
                except Exception:
                    pass
            # Ensure all UI events drained before next input
            await event_queue.join()

    except KeyboardInterrupt:
        log("Interrupted! Bye!")
        # Send interrupt to stop any running tasks
        try:
            await executor.submit({"type": "interrupt", "target_session_id": None})
        except:  # noqa: E722
            pass  # Executor might already be stopping
    finally:
        # Clean shutdown
        await executor.stop()
        executor_task.cancel()

        # Signal UI to stop
        await event_queue.put(EndEvent())
        await display_task


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


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Override model config name (uses main model by default)",
    ),
    select_model: bool = typer.Option(
        False,
        "--select-model",
        "-s",
        help="Interactively choose a model at startup",
    ),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
    continue_: bool = typer.Option(False, "--continue", "-c", help="Continue from latest session"),
    resume: bool = typer.Option(False, "--resume", "-r", help="Select a session to resume for this project"),
):
    """Root command callback. Runs interactive mode when no subcommand provided."""
    # Only run interactive mode when no subcommand is invoked
    if ctx.invoked_subcommand is None:
        chosen_model = model
        if select_model:
            # Prefer the explicitly provided model as default; otherwise main model
            default_name = model or load_config().main_model
            chosen_model = _select_model_from_config(preferred=default_name)
            if chosen_model is None:
                return

        # Resolve session id before entering asyncio loop
        session_id: str | None = None
        if resume:
            session_id = _resume_select_session()
            if session_id is None:
                return
        # If user didn't pick, allow fallback to --continue
        if session_id is None and continue_:
            session_id = Session.most_recent_session_id()

        asyncio.run(
            run_interactive(
                model=chosen_model,
                debug=debug,
                session_id=session_id,
            )
        )
