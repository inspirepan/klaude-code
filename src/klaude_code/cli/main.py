import asyncio
import datetime
import os
import subprocess
import sys
import uuid
from importlib.metadata import PackageNotFoundError, version as pkg_version

import typer

from klaude_code.cli.runtime import DEBUG_FILTER_HELP, AppInitConfig, resolve_debug_settings, run_exec, run_interactive
from klaude_code.cli.session_cmd import register_session_commands
from klaude_code.config import config_path, display_models_and_providers, load_config, select_model_from_config
from klaude_code.session import Session, resume_select_session
from klaude_code.trace import log
from klaude_code.ui.terminal.color import is_light_terminal_background


def set_terminal_title(title: str) -> None:
    """Set terminal window title using ANSI escape sequence."""
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()


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

session_app = typer.Typer(help="Manage sessions for the current project")
register_session_commands(session_app)
app.add_typer(session_app, name="session")


@app.command("login")
def login_command(
    provider: str = typer.Argument("codex", help="Provider to login (codex)"),
) -> None:
    """Login to a provider using OAuth."""
    if provider.lower() != "codex":
        log((f"Error: Unknown provider '{provider}'. Currently only 'codex' is supported.", "red"))
        raise typer.Exit(1)

    from klaude_code.auth.codex.oauth import CodexOAuth
    from klaude_code.auth.codex.token_manager import CodexTokenManager

    token_manager = CodexTokenManager()

    # Check if already logged in
    if token_manager.is_logged_in():
        state = token_manager.get_state()
        if state and not state.is_expired():
            log(("You are already logged in to Codex.", "green"))
            log(f"  Account ID: {state.account_id[:8]}...")
            expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.timezone.utc)
            log(f"  Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            if not typer.confirm("Do you want to re-login?"):
                return

    log("Starting Codex OAuth login flow...")
    log("A browser window will open for authentication.")

    try:
        oauth = CodexOAuth(token_manager)
        state = oauth.login()
        log(("Login successful!", "green"))
        log(f"  Account ID: {state.account_id[:8]}...")
        expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.timezone.utc)
        log(f"  Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    except Exception as e:
        log((f"Login failed: {e}", "red"))
        raise typer.Exit(1)


@app.command("logout")
def logout_command(
    provider: str = typer.Argument("codex", help="Provider to logout (codex)"),
) -> None:
    """Logout from a provider."""
    if provider.lower() != "codex":
        log((f"Error: Unknown provider '{provider}'. Currently only 'codex' is supported.", "red"))
        raise typer.Exit(1)

    from klaude_code.auth.codex.token_manager import CodexTokenManager

    token_manager = CodexTokenManager()

    if not token_manager.is_logged_in():
        log("You are not logged in to Codex.")
        return

    if typer.confirm("Are you sure you want to logout from Codex?"):
        token_manager.delete()
        log(("Logged out from Codex.", "green"))


@app.command("list")
def list_models() -> None:
    """List all models and providers configuration"""
    config = load_config()
    if config is None:
        raise typer.Exit(1)

    # Auto-detect theme when not explicitly set in config, to match other CLI entrypoints.
    if config.theme is None:
        detected = is_light_terminal_background()
        if detected is True:
            config.theme = "light"
        elif detected is False:
            config.theme = "dark"

    display_models_and_providers(config)


@app.command("config")
@app.command("conf", hidden=True)
def edit_config() -> None:
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
    stream_json: bool = typer.Option(
        False,
        "--stream-json",
        help="Stream all events as JSON lines to stdout.",
    ),
) -> None:
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
        except (OSError, ValueError) as e:
            # Expected I/O-related errors when reading from stdin (e.g. broken pipe, closed stream).
            log((f"Error reading from stdin: {e}", "red"))
        except Exception as e:
            # Unexpected errors are still reported but kept from crashing the CLI.
            log((f"Unexpected error reading from stdin: {e}", "red"))

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

    debug_enabled, debug_filters = resolve_debug_settings(debug, debug_filter)

    init_config = AppInitConfig(
        model=chosen_model,
        debug=debug_enabled,
        vanilla=vanilla,
        is_exec_mode=True,
        debug_filters=debug_filters,
        stream_json=stream_json,
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
) -> None:
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

        debug_enabled, debug_filters = resolve_debug_settings(debug, debug_filter)

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
