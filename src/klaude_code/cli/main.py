import asyncio
import sys

import typer

from klaude_code.cli.auth_cmd import register_auth_commands
from klaude_code.cli.config_cmd import register_config_commands
from klaude_code.cli.cost_cmd import register_cost_commands
from klaude_code.cli.debug import DEBUG_FILTER_HELP, prepare_debug_logging
from klaude_code.cli.self_update import register_self_update_commands, version_option_callback
from klaude_code.cli.session_cmd import register_session_commands
from klaude_code.session import Session
from klaude_code.tui.command.resume_cmd import select_session_sync
from klaude_code.ui.terminal.title import update_terminal_title

ENV_HELP = """\
Environment Variables:

  KLAUDE_READ_GLOBAL_LINE_CAP  Max lines to read (default: 2000)

  KLAUDE_READ_MAX_CHARS        Max total chars to read (default: 50000)
"""

app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
    epilog=ENV_HELP,
)

# Register subcommands from modules
register_session_commands(app)
register_auth_commands(app)
register_config_commands(app)
register_cost_commands(app)

register_self_update_commands(app)


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
        help="Vanilla mode exposes the model's raw API behavior: it provides only minimal tools (Bash, Read, Write & Edit) and omits system prompts and reminders.",
    ),
    banana: bool = typer.Option(
        False,
        "--banana",
        help="Image generation mode with Nano Banana",
        rich_help_panel="LLM",
    ),
) -> None:
    # Only run interactive mode when no subcommand is invoked
    if ctx.invoked_subcommand is None:
        from klaude_code.log import log

        if vanilla and banana:
            log(("Error: --banana cannot be combined with --vanilla", "red"))
            raise typer.Exit(2)

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

        if not sys.stdin.isatty() or not sys.stdout.isatty():
            log(("Error: interactive mode requires a TTY", "red"))
            log(("Hint: run klaude from an interactive terminal", "yellow"))
            raise typer.Exit(2)

        from klaude_code.app.runtime import AppInitConfig
        from klaude_code.tui.command.model_select import select_model_interactive
        from klaude_code.tui.runner import run_interactive

        update_terminal_title()

        chosen_model = model
        if banana:
            # Banana mode always uses the built-in Nano Banana Pro image model.
            chosen_model = "nano-banana-pro@or"
        elif model or select_model:
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
            from klaude_code.log import log

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
                from klaude_code.log import log

                asyncio.run(cfg.save())
                log(f"Saved main_model={chosen_model} to {config_path}", style="dim")

        debug_enabled, debug_filters, log_path = prepare_debug_logging(debug, debug_filter)

        init_config = AppInitConfig(
            model=chosen_model,
            debug=debug_enabled,
            vanilla=vanilla,
            banana=banana,
            debug_filters=debug_filters,
        )

        if log_path:
            log(f"Debug log: {log_path}", style="dim")

        asyncio.run(
            run_interactive(
                init_config=init_config,
                session_id=session_id,
            )
        )
