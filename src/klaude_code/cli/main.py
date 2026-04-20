import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import typer
from typer.core import TyperGroup

from klaude_code.cli.auth_cmd import register_auth_commands
from klaude_code.cli.config_cmd import register_config_commands
from klaude_code.cli.self_update import register_self_upgrade_commands, version_option_callback


class _LazyEnvHelp:
    """Lazy proxy that defers heavy config imports until --help is shown.

    Typer/Click calls .split() and str() on the epilog, so we materialise
    the real string on first attribute access.
    """

    _value: str | None = None

    def _resolve(self) -> str:
        if self._value is None:
            from klaude_code.config.builtin_config import SUPPORTED_API_KEYS

            lines = [
                "Environment Variables:",
                "",
                "Provider API keys (built-in config):",
            ]
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
                ]
            )
            self._value = "\n\n".join(lines)
        return self._value

    def __str__(self) -> str:
        return self._resolve()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)


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


def prepare_debug_logging(debug: bool) -> tuple[bool, Path | None]:
    from klaude_code.cli.debug import prepare_debug_logging as _prepare_debug_logging

    return _prepare_debug_logging(debug)


def run_web_server_command(*, host: str, port: int, no_open: bool, debug: bool) -> None:
    from klaude_code.cli.web_cmd import run_web_server_command as _run_web_server_command

    _run_web_server_command(host=host, port=port, no_open=no_open, debug=debug)


def _maybe_auto_upgrade_and_reexec() -> None:
    """Perform an in-place upgrade before entering the interactive loop.

    Controlled by ``Config.auto_upgrade`` (default True). Only runs when the
    persisted update state indicates a newer release is available. Re-executes
    the current process on success so the new version is loaded.
    """

    try:
        from klaude_code.config import load_config
    except Exception:
        return

    try:
        cfg = load_config()
    except Exception:
        return
    if not cfg.auto_upgrade:
        return

    from klaude_code.log import log
    from klaude_code.update import perform_auto_upgrade_if_needed, reexec_after_auto_upgrade

    result = perform_auto_upgrade_if_needed()
    if result.message:
        log((result.message, "yellow" if result.level == "warn" else "cyan"))
    if result.performed:
        reexec_after_auto_upgrade()


app = typer.Typer(
    cls=_PreprocessingTyperGroup,
    add_completion=False,
    pretty_exceptions_enable=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
    epilog=cast(str, _LazyEnvHelp()),
    context_settings={"help_option_names": ["-h", "--help"]},
)

# Register subcommands from modules
register_auth_commands(app)
register_config_commands(app)
register_self_upgrade_commands(app)


@app.command("web")
def _web_command_wrapper(  # pyright: ignore[reportUnusedFunction]
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind web server"),
    port: int = typer.Option(8765, "--port", help="Port to bind web server"),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open browser automatically"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logs for web server"),
) -> None:
    run_web_server_command(host=host, port=port, no_open=no_open, debug=debug)


# cost command is registered via a lazy wrapper to avoid pulling in
# klaude_code.protocol at import time (~200ms).
@app.command("cost")
def _cost_command_wrapper(  # pyright: ignore[reportUnusedFunction]
    days: int = typer.Option(7, "--days", "-d", "--recent", help="Limit to last N days"),
    show_all: bool = typer.Option(False, "--all", help="Show all usage data"),
) -> None:
    """Show usage stats"""
    from klaude_code.cli.cost_cmd import cost_command

    cost_command(days=days, show_all=show_all)


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
        help="Open model picker; pass a value to prefill search, or use --model with no value to start empty",
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
    vanilla: bool = typer.Option(
        False,
        "--vanilla",
        help="Minimal mode: basic tools only, no system prompts",
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
        from klaude_code.session import Session
        from klaude_code.tui.terminal.session_selector import select_session_sync
        from klaude_code.tui.terminal.title import update_terminal_title

        resume_by_id_value = resume_by_id.strip() if resume_by_id is not None else None
        if resume_by_id_value == "":
            log(("Error: --resume <id> cannot be empty", "red"))
            raise typer.Exit(2)

        if resume_by_id_value is not None and (resume or continue_):
            log(("Error: --resume <id> cannot be combined with --continue or interactive --resume", "red"))
            raise typer.Exit(2)

        # Resolve resume_by_id with prefix matching support
        if resume_by_id_value is not None and not Session.exists(resume_by_id_value, work_dir=Path.cwd()):
            matches = Session.find_sessions_by_prefix(resume_by_id_value, work_dir=Path.cwd())
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

        _maybe_auto_upgrade_and_reexec()

        from klaude_code.app.runtime import AppInitConfig
        from klaude_code.tui.command.model_picker import ModelSelectStatus, select_model_interactive
        from klaude_code.tui.runner import run_interactive

        update_terminal_title()

        chosen_model = model
        if model or select_model:
            initial_search_text = (model.strip() or None) if model is not None else None
            model_result = select_model_interactive(initial_search_text=initial_search_text)
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
            session_id = Session.most_recent_session_id(work_dir=Path.cwd())

        if resume_by_id_value is not None:
            session_id = resume_by_id_value
        # If still no session_id, leave as None to create a new session

        if session_id is not None and chosen_model is None:
            from klaude_code.config import load_config
            from klaude_code.log import log

            session_meta = Session.load_meta(session_id, work_dir=Path.cwd())
            cfg = load_config()
            main_model = (cfg.main_model.strip() or None) if cfg.main_model else None

            if session_meta.model_config_name:
                session_model = session_meta.model_config_name.strip()
                try:
                    model_is_available = (
                        bool(session_model) and cfg.resolve_model_location_prefer_available(session_model) is not None
                    )
                except ValueError:
                    model_is_available = False

                if model_is_available:
                    chosen_model = session_model
                else:
                    log(
                        (
                            f"Warning: session model '{session_meta.model_config_name}' is not currently available",
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

            if chosen_model is None:
                chosen_model = main_model

        # If still no model, check main_model; if not configured, trigger interactive selection
        if chosen_model is None:
            from klaude_code.config import load_config

            cfg = load_config()
            main_model = (cfg.main_model.strip() or None) if cfg.main_model else None
            if main_model is None:
                model_result = select_model_interactive()
                if model_result.status != ModelSelectStatus.SELECTED or model_result.model is None:
                    raise typer.Exit(1)
                chosen_model = model_result.model
                # Save the selection as default
                cfg.main_model = chosen_model
                from klaude_code.config.config import config_path
                from klaude_code.log import log

                asyncio.run(cfg.save())
                log(f"Saved main_model={chosen_model} to {config_path}")
            else:
                chosen_model = main_model

        debug_enabled, log_path = prepare_debug_logging(debug)

        init_config = AppInitConfig(
            model=chosen_model,
            debug=debug_enabled,
            vanilla=vanilla,
        )

        if log_path:
            log(f"Debug log: {log_path}")

            from klaude_code.app.log_viewer import start_log_viewer

            viewer_url = start_log_viewer(log_path)
            log(f"Log viewer: {viewer_url}")

        web_mode_request = asyncio.run(
            run_interactive(
                init_config=init_config,
                session_id=session_id,
            )
        )
        if web_mode_request is not None:
            run_web_server_command(
                host=web_mode_request.host,
                port=web_mode_request.port,
                no_open=web_mode_request.no_open,
                debug=web_mode_request.debug if web_mode_request.debug is not None else debug_enabled,
            )
