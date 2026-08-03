import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import click
import typer
from typer.core import TyperGroup

from klaude_code.cli.agents_cmd import register_agents_command
from klaude_code.cli.attach_cmd import register_attach_command
from klaude_code.cli.auth_cmd import register_auth_commands
from klaude_code.cli.config_cmd import register_config_commands
from klaude_code.cli.headless_cmd import register_headless_commands
from klaude_code.cli.self_update import register_self_upgrade_commands, version_option_callback
from klaude_code.cli.server_cmd import register_server_commands

# Product spec: docs/agent-multiplexer.md §2. Plain text on purpose — help is
# read by agents as often as by humans, so no rich panels or box drawing.
TOP_LEVEL_HELP = """\
Usage: klaude [OPTIONS] [COMMAND]

klaude — an agent multiplexer.

Run coding agents interactively, in the background, or from other
agents. A single local server owns all execution; the TUI and every
CLI command below are clients of it. Running klaude with no command
opens an interactive session in the current directory (the server is
auto-started when needed).

Options:
  -c, --continue       Resume the latest session in this directory
  -r, --resume [ID]    Pick a session and resume it
  -m, --model TEXT     Select model (see `klaude agents`)
      --vanilla        Minimal mode: basic tools, no system prompts
  -d, --debug          Enable debug logging
  -V, --version        Show version and exit
  -h, --help           Show this message and exit

Background agents:
  run        Spawn a background agent, print its id, return at once
  ps         List sessions and their runtime states
  brief      Compact status of one session (agent-friendly, bounded)
  wait       Block until agents finish; print their results
  output     Print a session's output (last reply / transcript)
  send       Send a follow-up message (queued by default)
  respond    Answer a pending approval/question of a session
  kill       Interrupt a running agent (session stays resumable)

Attach:
  attach     Open the TUI on a session: replay, then follow live

Discovery:
  agents     Show agent types and models; --json for machines,
             --prime for an AI-agent integration guide

Server:
  server     Manage the local server (status / stop / reload / logs / run)

Setup:
  conf       Edit config file
  auth       Login/logout
  cost       Show usage stats
  upgrade    Upgrade to latest version

TARGET accepts a session id (unique prefix is enough) or a --name
given at `klaude run`. Pass --json to any background-agent or
discovery command for machine-readable output.

Orchestration is plain bash: `run` returns immediately, multi-target
`wait` is a barrier, `--group` names a fan-out. For the playbook
(parallel fan-out, barriers, loops, synthesis pipelines) and the
current model/agent inventory, run: klaude agents --prime
"""


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
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        del ctx
        formatter.write(TOP_LEVEL_HELP)

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


def _maybe_start_auto_upgrade() -> None:
    """Start auto-upgrade in the background for interactive startup.

    Controlled by ``Config.auto_upgrade`` (default True). Only attempts an
    upgrade when the persisted update state indicates a newer release is
    available. Any successful upgrade applies on the next process start.
    """

    try:
        from klaude_code.config import load_config
    except Exception:
        return

    try:
        cfg = load_config()
        if not cfg.auto_upgrade:
            return
    except Exception:
        return

    from klaude_code.update import start_background_auto_upgrade_if_needed

    start_background_auto_upgrade_if_needed()


app = typer.Typer(
    cls=_PreprocessingTyperGroup,
    add_completion=False,
    pretty_exceptions_enable=False,
    no_args_is_help=False,
    rich_markup_mode=None,
    context_settings={"help_option_names": ["-h", "--help"]},
)

# Register subcommands from modules
register_auth_commands(app)
register_config_commands(app)
register_self_upgrade_commands(app)
register_server_commands(app)
register_headless_commands(app)
register_attach_command(app)
register_agents_command(app)


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
        help="Select model; pass a value to auto-select on unique match or prefill the picker search, or use --model with no value to open the picker",
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

        _maybe_start_auto_upgrade()

        from klaude_code.tui.command.model_picker import ModelSelectStatus, select_model_interactive

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
            from klaude_code.config import ConfigValidationError, load_config
            from klaude_code.log import log

            session_meta = Session.load_meta(session_id, work_dir=Path.cwd())
            try:
                cfg = load_config()
            except ConfigValidationError as exc:
                log((str(exc), "red"))
                sys.exit(1)

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

            # If session didn't resolve a model, fall through to the main_model
            # validation block below so an invalid main_model triggers the same
            # error + picker flow as when chosen_model starts out None.

        # If still no model, check main_model; if not configured or invalid,
        # trigger interactive selection.
        if chosen_model is None:
            from klaude_code.config import (
                ConfigValidationError,
                ModelAvailability,
                format_model_preference,
                load_config,
            )

            try:
                cfg = load_config()
            except ConfigValidationError as exc:
                from klaude_code.log import log

                log((str(exc), "red"))
                sys.exit(1)
            main_model = cfg.main_model

            picker_highlighted: list[str] | None = None
            picker_initial: str | None = None
            needs_picker = main_model is None

            if main_model is not None:
                main_candidates = (
                    cfg.iter_model_config_candidates(main_model)
                    if hasattr(cfg, "iter_model_config_candidates")
                    else None
                )
                if main_candidates == []:
                    main_display = format_model_preference(main_model) or ""
                    from klaude_code.log import log

                    if isinstance(main_model, str):
                        diag = cfg.diagnose_model(main_model)
                        log((f"Error: main_model '{main_display}' is unavailable ({diag.detail})", "red"))
                        if diag.availability != ModelAvailability.AVAILABLE and diag.suggestions:
                            log(("Did you mean: " + ", ".join(diag.suggestions) + " ?", "yellow"))
                            picker_highlighted = diag.suggestions or None
                            picker_initial = diag.suggestions[0] if diag.suggestions else None
                    else:
                        log((f"Error: main_model '{main_display}' has no available candidates", "red"))
                    needs_picker = True

            if needs_picker:
                model_result = select_model_interactive(
                    highlighted_selectors=picker_highlighted,
                    initial_selector=picker_initial,
                )
                if model_result.status != ModelSelectStatus.SELECTED or model_result.model is None:
                    raise typer.Exit(1)
                chosen_model = model_result.model
                # Save the selection as default
                cfg.main_model = chosen_model
                from klaude_code.config.config import config_path
                from klaude_code.log import log

                asyncio.run(cfg.save())
                log(f"Saved main_model={chosen_model} to {config_path}")
            elif isinstance(main_model, str):
                chosen_model = main_model

        _debug_enabled, log_path = prepare_debug_logging(debug)

        if log_path:
            log(f"Debug log: {log_path}")

            from klaude_code.app.log_viewer import start_log_viewer

            viewer_url = start_log_viewer(log_path)
            log(f"Log viewer: {viewer_url}")

        # TUI = client of the single local server: auto-start it, create the
        # session server-side when needed, then attach (replay + live).
        from klaude_code.cli.uds_client import ServerNotRunningError, ensure_server_running
        from klaude_code.tui.runner import run_attach

        try:
            ensure_server_running()
        except ServerNotRunningError as exc:
            log((f"Error: could not start the klaude server: {exc}", "red"))
            log(("Hint: run `klaude server run` in another terminal to see why", "yellow"))
            raise typer.Exit(1) from None

        if session_id is None:
            from klaude_code.cli.uds_client import request

            status, body = request(
                "POST",
                "/api/sessions",
                json_body={"work_dir": str(Path.cwd()), "model": chosen_model, "vanilla": vanilla},
            )
            if status != 200 or not isinstance(body, dict) or not body.get("session_id"):
                detail = body.get("detail") if isinstance(body, dict) else body
                log((f"Error: failed to create session: {detail}", "red"))
                raise typer.Exit(1)
            session_id = str(body["session_id"])
        elif chosen_model:
            # Resuming: persist the resolved model (explicit -m, the session's
            # own model, or the fallback) so the server rehydrates with it.
            from klaude_code.session.store_registry import get_store_for_path

            get_store_for_path(Path.cwd()).update_meta(session_id, {"model_config_name": chosen_model})

        asyncio.run(run_attach(session_id))
