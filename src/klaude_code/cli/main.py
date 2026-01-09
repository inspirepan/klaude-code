import asyncio
import sys
from collections.abc import Sequence
from typing import Any

import typer
from typer.core import TyperGroup

from klaude_code.cli.auth_cmd import register_auth_commands
from klaude_code.cli.config_cmd import register_config_commands
from klaude_code.cli.cost_cmd import register_cost_commands
from klaude_code.cli.debug import DEBUG_FILTER_HELP, prepare_debug_logging
from klaude_code.cli.self_update import register_self_upgrade_commands, version_option_callback
from klaude_code.session import Session
from klaude_code.tui.command.resume_cmd import select_session_sync
from klaude_code.ui.terminal.title import update_terminal_title


def _build_env_help() -> str:
    from klaude_code.config.builtin_config import SUPPORTED_API_KEYS

    lines = [
        "Environment Variables:",
        "",
        "Provider API keys (built-in config):",
    ]
    # Calculate max env_var length for alignment
    max_len = max(len(k.env_var) for k in SUPPORTED_API_KEYS)
    for k in SUPPORTED_API_KEYS:
        lines.append(f"  {k.env_var:<{max_len}}  {k.description}")
    lines.extend(
        [
            "",
            "Tool limits (Read):",
            "  KLAUDE_READ_GLOBAL_LINE_CAP    Max lines to read (default: 2000)",
            "  KLAUDE_READ_MAX_CHARS          Max total chars to read (default: 50000)",
            "  KLAUDE_READ_MAX_IMAGE_BYTES    Max image bytes to read (default: 64MB)",
            "  KLAUDE_IMAGE_OUTPUT_MAX_BYTES  Max decoded image bytes (default: 64MB)",
        ]
    )
    return "\n\n".join(lines)


ENV_HELP = _build_env_help()


def _looks_like_flag(token: str) -> bool:
    return token.startswith("-") and token != "-"


def _preprocess_cli_args(args: list[str]) -> list[str]:
    """Rewrite CLI args to support optional values for selected options.

    Supported rewrites:
    - --model / -m with no value -> --model-select
    - --resume / -r with value -> --resume-by-id <value>
    """

    rewritten: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]

        if token in {"--model", "-m"}:
            next_token = args[i + 1] if i + 1 < len(args) else None
            if next_token is None or next_token == "--" or _looks_like_flag(next_token):
                rewritten.append("--model-select")
                i += 1
                continue
            rewritten.append(token)
            i += 1
            continue

        if token.startswith("--model="):
            value = token.split("=", 1)[1]
            if value == "":
                rewritten.append("--model-select")
            else:
                rewritten.append(token)
            i += 1
            continue

        if token in {"--resume", "-r"}:
            next_token = args[i + 1] if i + 1 < len(args) else None
            if next_token is not None and next_token != "--" and not _looks_like_flag(next_token):
                rewritten.extend(["--resume-by-id", next_token])
                i += 2
                continue
            rewritten.append(token)
            i += 1
            continue

        if token.startswith("--resume="):
            value = token.split("=", 1)[1]
            rewritten.extend(["--resume-by-id", value])
            i += 1
            continue

        rewritten.append(token)
        i += 1

    return rewritten


class _PreprocessingTyperGroup(TyperGroup):
    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        click_args = _preprocess_cli_args(list(args) if args is not None else sys.argv[1:])
        return super().main(
            args=click_args,
            prog_name=prog_name,
            complete_var=complete_var,
            standalone_mode=standalone_mode,
            windows_expand_args=windows_expand_args,
            **extra,
        )


app = typer.Typer(
    cls=_PreprocessingTyperGroup,
    add_completion=False,
    pretty_exceptions_enable=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
    epilog=ENV_HELP,
    context_settings={"help_option_names": ["-h", "--help"]},
)

# Register subcommands from modules
register_auth_commands(app)
register_config_commands(app)
register_cost_commands(app)
register_self_upgrade_commands(app)


@app.command("help", hidden=True)
def help_command(ctx: typer.Context) -> None:
    """Show help message."""
    print(ctx.parent.get_help() if ctx.parent else ctx.get_help())


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Select model by name; use --model with no value to choose interactively",
        rich_help_panel="LLM",
    ),
    continue_: bool = typer.Option(False, "--continue", "-c", help="Resume latest session"),
    resume: bool = typer.Option(
        False,
        "--resume",
        "-r",
        help="Resume a session; use --resume <id> to resume directly, or --resume to pick interactively",
    ),
    resume_by_id: str | None = typer.Option(
        None,
        "--resume-by-id",
        help="Resume session by ID",
        hidden=True,
    ),
    select_model: bool = typer.Option(
        False,
        "--model-select",
        help="Choose model interactively (same as --model with no value)",
        hidden=True,
        rich_help_panel="LLM",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        "-d",
        help="Enable debug logging",
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
        help="Minimal mode: basic tools only, no system prompts",
    ),
    banana: bool = typer.Option(
        False,
        "--banana",
        help="Image generation mode (alias for --model banana)",
        rich_help_panel="LLM",
    ),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        "-v",
        help="Show version and exit",
        callback=version_option_callback,
        is_eager=True,
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
            log(("Error: --resume <id> cannot be empty", "red"))
            raise typer.Exit(2)

        if resume_by_id_value is not None and (resume or continue_):
            log(("Error: --resume <id> cannot be combined with --continue or interactive --resume", "red"))
            raise typer.Exit(2)

        # Resolve resume_by_id with prefix matching support
        if resume_by_id_value is not None and not Session.exists(resume_by_id_value):
            matches = Session.find_sessions_by_prefix(resume_by_id_value)
            if not matches:
                log((f"Error: session id '{resume_by_id_value}' not found for this project", "red"))
                log(("Hint: run `klaude --resume` to select an existing session", "yellow"))
                raise typer.Exit(2)
            if len(matches) == 1:
                resume_by_id_value = matches[0]
            else:
                # Multiple matches: show interactive selection with filtered list
                selected = select_session_sync(session_ids=matches)
                if selected is None:
                    raise typer.Exit(1)
                resume_by_id_value = selected

        if not sys.stdin.isatty() or not sys.stdout.isatty():
            log(("Error: interactive mode requires a TTY", "red"))
            log(("Hint: run klaude from an interactive terminal", "yellow"))
            raise typer.Exit(2)

        from klaude_code.app.runtime import AppInitConfig
        from klaude_code.tui.command.model_picker import ModelSelectStatus, select_model_interactive
        from klaude_code.tui.runner import run_interactive

        update_terminal_title()

        chosen_model = model
        if banana:
            keywords = ["gemini-3-pro-image", "gemini-2.5-flash-image"]
            model_result = select_model_interactive(keywords=keywords)
            if model_result.status == ModelSelectStatus.SELECTED and model_result.model is not None:
                chosen_model = model_result.model
            elif model_result.status == ModelSelectStatus.CANCELLED:
                return
            else:
                log(("Error: no available nano-banana model", "red"))
                log(("Hint: set OPENROUTER_API_KEY or GOOGLE_API_KEY to enable nano-banana models", "yellow"))
                raise typer.Exit(2)
        elif model or select_model:
            model_result = select_model_interactive(preferred=model)
            if model_result.status == ModelSelectStatus.SELECTED and model_result.model is not None:
                chosen_model = model_result.model
            else:
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
                try:
                    model_is_known = cfg.has_model_config_name(session_meta.model_config_name)
                except ValueError:
                    model_is_known = False

                if model_is_known:
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
                        m.selector
                        for m in cfg.iter_model_entries(only_available=True, include_disabled=False)
                        if (m.model_id or "").strip().lower() == raw_model.lower()
                    ]
                    if len(matches) == 1:
                        chosen_model = matches[0]

        # If still no model, check main_model; if not configured, trigger interactive selection
        if chosen_model is None:
            from klaude_code.config import load_config

            cfg = load_config()
            if cfg.main_model is None:
                model_result = select_model_interactive()
                if model_result.status != ModelSelectStatus.SELECTED or model_result.model is None:
                    raise typer.Exit(1)
                chosen_model = model_result.model
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
            debug_filters=debug_filters,
        )

        if log_path:
            log(f"Debug log: {log_path}", style="red")

        asyncio.run(
            run_interactive(
                init_config=init_config,
                session_id=session_id,
            )
        )
