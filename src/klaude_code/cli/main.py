import asyncio
import contextlib
import os
import sys
from pathlib import Path

import typer

from klaude_code.cli.auth_cmd import register_auth_commands
from klaude_code.cli.config_cmd import register_config_commands
from klaude_code.cli.debug import DEBUG_FILTER_HELP, open_log_file_in_editor, resolve_debug_settings
from klaude_code.cli.self_update import register_self_update_commands, version_option_callback
from klaude_code.cli.session_cmd import register_session_commands
from klaude_code.command.resume_cmd import select_session_sync
from klaude_code.session import Session
from klaude_code.trace import DebugType, prepare_debug_log_file


def set_terminal_title(title: str) -> None:
    """Set terminal window title using ANSI escape sequence."""
    # Never write terminal control sequences when stdout is not a TTY (pipes/CI/redirects).
    # This avoids corrupting machine-readable output (e.g., JSON streaming) and log captures.
    #
    # Use the original stdout to bypass prompt_toolkit's `patch_stdout()`. Writing OSC
    # sequences to the patched stdout can cause them to appear as visible text.
    stream = getattr(sys, "__stdout__", None) or sys.stdout
    try:
        if not stream.isatty():
            return
    except Exception:
        return

    stream.write(f"\033]0;{title}\007")
    with contextlib.suppress(Exception):
        stream.flush()


def update_terminal_title(model_name: str | None = None) -> None:
    """Update terminal title with folder name and optional model name."""
    folder_name = os.path.basename(os.getcwd())
    if model_name:
        set_terminal_title(f"{folder_name}: klaude ✳ {model_name}")
    else:
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


app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    no_args_is_help=False,
)

# Register subcommands from modules
register_session_commands(app)
register_auth_commands(app)
register_config_commands(app)

register_self_update_commands(app)


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
    update_terminal_title()

    merged_input = read_input_content(input_content)
    if merged_input is None:
        raise typer.Exit(1)

    from klaude_code.cli.runtime import AppInitConfig, run_exec
    from klaude_code.command.model_select import select_model_interactive
    from klaude_code.config import load_config

    chosen_model = model
    if model or select_model:
        chosen_model = select_model_interactive(preferred=model)
        if chosen_model is None:
            raise typer.Exit(1)
    else:
        # Check if main_model is configured; if not, trigger interactive selection
        config = load_config()
        if config.main_model is None:
            chosen_model = select_model_interactive()
            if chosen_model is None:
                raise typer.Exit(1)
            # Save the selection as default
            config.main_model = chosen_model
            from klaude_code.config.config import config_path
            from klaude_code.trace import log

            asyncio.run(config.save())
            log(f"Saved main_model={chosen_model} to {config_path}", style="cyan")

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
        "-v",
        help="Show version and exit",
        callback=version_option_callback,
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
    resume_by_id: str | None = typer.Option(
        None,
        "--resume-by-id",
        help="Resume a session by its ID (must exist)",
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
) -> None:
    # Only run interactive mode when no subcommand is invoked
    if ctx.invoked_subcommand is None:
        from klaude_code.trace import log

        resume_by_id_value = resume_by_id.strip() if resume_by_id is not None else None
        if resume_by_id_value == "":
            log(("Error: --resume-by-id cannot be empty", "red"))
            raise typer.Exit(2)

        if resume_by_id_value is not None and (resume or continue_):
            log(("Error: --resume-by-id cannot be combined with --resume/--continue", "red"))
            raise typer.Exit(2)

        if resume_by_id_value is not None and not Session.exists(resume_by_id_value):
            log((f"Error: session id '{resume_by_id_value}' not found for this project", "red"))
            log(("Hint: run `klaude --resume` to select an existing session", "yellow"))
            raise typer.Exit(2)

        # In non-interactive environments, default to exec-mode behavior.
        # This allows: echo "..." | klaude
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            if continue_ or resume or resume_by_id is not None:
                log(("Error: --continue/--resume options require a TTY", "red"))
                log(("Hint: use `klaude exec` for non-interactive usage", "yellow"))
                raise typer.Exit(2)

            exec_command(
                input_content="",
                model=model,
                select_model=select_model,
                debug=debug,
                debug_filter=debug_filter,
                vanilla=vanilla,
                stream_json=False,
            )
            return

        from klaude_code.cli.runtime import AppInitConfig, run_interactive
        from klaude_code.command.model_select import select_model_interactive

        update_terminal_title()

        chosen_model = model
        if model or select_model:
            chosen_model = select_model_interactive(preferred=model)
            if chosen_model is None:
                return

        # Resolve session id before entering asyncio loop
        # session_id=None means create a new session
        session_id: str | None = None

        if resume:
            session_id = select_session_sync()
            if session_id is None:
                return
        # If user didn't pick, allow fallback to --continue
        if session_id is None and continue_:
            session_id = Session.most_recent_session_id()

        if resume_by_id_value is not None:
            session_id = resume_by_id_value
        # If still no session_id, leave as None to create a new session

        if session_id is not None and chosen_model is None:
            from klaude_code.config import load_config
            from klaude_code.trace import log

            session_meta = Session.load_meta(session_id)
            cfg = load_config()

            if session_meta.model_config_name:
                if any(m.model_name == session_meta.model_config_name for m in cfg.iter_model_entries()):
                    chosen_model = session_meta.model_config_name
                else:
                    log(
                        (
                            f"Warning: session model '{session_meta.model_config_name}' is not defined in config; falling back to default",
                            "yellow",
                        )
                    )

            if chosen_model is None and session_meta.model_name:
                raw_model = session_meta.model_name.strip()
                if raw_model:
                    matches = [
                        m.model_name
                        for m in cfg.iter_model_entries()
                        if (m.model_params.model or "").strip().lower() == raw_model.lower()
                    ]
                    if len(matches) == 1:
                        chosen_model = matches[0]

        # If still no model, check main_model; if not configured, trigger interactive selection
        if chosen_model is None:
            from klaude_code.config import load_config

            cfg = load_config()
            if cfg.main_model is None:
                chosen_model = select_model_interactive()
                if chosen_model is None:
                    raise typer.Exit(1)
                # Save the selection as default
                cfg.main_model = chosen_model
                from klaude_code.config.config import config_path
                from klaude_code.trace import log

                asyncio.run(cfg.save())
                log(f"Saved main_model={chosen_model} to {config_path}", style="dim")

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
