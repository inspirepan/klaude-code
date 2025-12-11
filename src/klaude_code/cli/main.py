import asyncio
import os
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path

import typer

from klaude_code.cli.auth_cmd import register_auth_commands
from klaude_code.cli.config_cmd import register_config_commands
from klaude_code.cli.debug import DEBUG_FILTER_HELP, open_log_file_in_editor, resolve_debug_settings
from klaude_code.cli.session_cmd import register_session_commands
from klaude_code.session import Session, resume_select_session
from klaude_code.trace import DebugType, prepare_debug_log_file


def set_terminal_title(title: str) -> None:
    """Set terminal window title using ANSI escape sequence."""
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()


def setup_terminal_title() -> None:
    """Set terminal title to current folder name."""
    folder_name = os.path.basename(os.getcwd())
    set_terminal_title(f"{folder_name}: klaude")


def prepare_debug_logging(debug: bool, debug_filter: str | None) -> tuple[bool, set[DebugType] | None, Path | None]:
    """Resolve debug settings and prepare log file if debugging is enabled.

    Returns:
        A tuple of (debug_enabled, debug_filters, log_path).
        log_path is None if debugging is disabled.
    """
    debug_enabled, debug_filters = resolve_debug_settings(debug, debug_filter)
    log_path: Path | None = None
    if debug_enabled:
        log_path = prepare_debug_log_file()
    return debug_enabled, debug_filters, log_path


def read_input_content(cli_argument: str) -> str | None:
    """Read and merge input from stdin and CLI argument.

    Args:
        cli_argument: The input content passed as CLI argument.

    Returns:
        The merged input content, or None if no input was provided.
    """
    from klaude_code.trace import log

    parts: list[str] = []

    # Handle stdin input
    if not sys.stdin.isatty():
        try:
            stdin = sys.stdin.read().rstrip("\n")
            if stdin:
                parts.append(stdin)
        except (OSError, ValueError) as e:
            # Expected I/O-related errors when reading from stdin (e.g. broken pipe, closed stream).
            log((f"Error reading from stdin: {e}", "red"))
        except Exception as e:
            # Unexpected errors are still reported but kept from crashing the CLI.
            log((f"Unexpected error reading from stdin: {e}", "red"))

    if cli_argument:
        parts.append(cli_argument)

    content = "\n".join(parts)
    if len(content) == 0:
        log(("Error: No input content provided", "red"))
        return None

    return content


def _version_callback(value: bool) -> None:
    """Show version and exit."""
    if value:
        try:
            ver = pkg_version("klaude-code")
        except PackageNotFoundError:
            # Package is not installed or has no metadata; show a generic version string.
            ver = "unknown"
        except Exception:
            ver = "unknown"
        print(f"klaude-code {ver}")
        raise typer.Exit(0)


app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    no_args_is_help=False,
)

# Register subcommands from modules
register_session_commands(app)
register_auth_commands(app)
register_config_commands(app)


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
    stream_json: bool = typer.Option(
        False,
        "--stream-json",
        help="Stream all events as JSON lines to stdout.",
    ),
) -> None:
    """Execute non-interactively with provided input."""
    setup_terminal_title()

    merged_input = read_input_content(input_content)
    if merged_input is None:
        raise typer.Exit(1)

    from klaude_code.cli.runtime import AppInitConfig, run_exec
    from klaude_code.config.select_model import select_model_from_config

    chosen_model = model
    if model or select_model:
        chosen_model = select_model_from_config(preferred=model)
        if chosen_model is None:
            return

    debug_enabled, debug_filters, log_path = prepare_debug_logging(debug, debug_filter)

    init_config = AppInitConfig(
        model=chosen_model,
        debug=debug_enabled,
        vanilla=vanilla,
        is_exec_mode=True,
        debug_filters=debug_filters,
        stream_json=stream_json,
    )

    if log_path:
        open_log_file_in_editor(log_path)

    asyncio.run(
        run_exec(
            init_config=init_config,
            input_content=merged_input,
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
) -> None:
    # Only run interactive mode when no subcommand is invoked
    if ctx.invoked_subcommand is None:
        from klaude_code.cli.runtime import AppInitConfig, run_interactive
        from klaude_code.config.select_model import select_model_from_config

        setup_terminal_title()

        chosen_model = model
        if model or select_model:
            chosen_model = select_model_from_config(preferred=model)
            if chosen_model is None:
                return

        # Resolve session id before entering asyncio loop
        # session_id=None means create a new session
        session_id: str | None = None
        if resume:
            session_id = resume_select_session()
            if session_id is None:
                return
        # If user didn't pick, allow fallback to --continue
        if session_id is None and continue_:
            session_id = Session.most_recent_session_id()
        # If still no session_id, leave as None to create a new session

        debug_enabled, debug_filters, log_path = prepare_debug_logging(debug, debug_filter)

        init_config = AppInitConfig(
            model=chosen_model,
            debug=debug_enabled,
            vanilla=vanilla,
            debug_filters=debug_filters,
        )

        if log_path:
            open_log_file_in_editor(log_path)

        asyncio.run(
            run_interactive(
                init_config=init_config,
                session_id=session_id,
            )
        )
