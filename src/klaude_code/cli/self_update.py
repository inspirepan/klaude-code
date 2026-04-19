"""Self-update and version utilities for klaude-code."""

import shutil
import subprocess
from pathlib import Path

import typer


def _print_version() -> None:
    from klaude_code.update import PACKAGE_NAME, get_display_version

    print(f"{PACKAGE_NAME} {get_display_version()}")


def version_option_callback(value: bool) -> None:
    """Show version and exit."""
    if value:
        _print_version()
        raise typer.Exit(0)


def version_command() -> None:
    """Show version and exit."""

    _print_version()


def _upgrade_local_git_install(install_kind: str, source_path: str) -> None:
    from klaude_code.log import log
    from klaude_code.update import INSTALL_KIND_EDITABLE

    repo_path = Path(source_path).expanduser()
    source_display = str(repo_path)

    if not repo_path.exists() or not repo_path.is_dir():
        log((f"Error: local source path is unavailable: {source_display}", "red"))
        raise typer.Exit(1)

    if shutil.which("uv") is None:
        log(("Error: `uv` not found in PATH.", "red"))
        log(f"To update, install uv and run `uv tool install {source_display}`.")
        raise typer.Exit(1)

    try:
        status_result = subprocess.run(
            ["git", "-C", source_display, "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as err:
        log(("Error: `git` not found in PATH.", "red"))
        raise typer.Exit(1) from err

    if status_result.returncode != 0:
        log((f"Error: local source is not a git repository: {source_display}", "red"))
        log("Please update the source manually and reinstall if needed.")
        raise typer.Exit(1)

    if status_result.stdout.strip():
        log(("Error: local git checkout has uncommitted changes.", "red"))
        log(f"Source path: {source_display}")
        log("Commit or stash your changes, then run `klaude upgrade` again.")
        raise typer.Exit(1)

    log(f"Updating local source at {source_display}…")
    log("Switching local checkout to `main`…")
    checkout_result = subprocess.run(["git", "-C", source_display, "checkout", "main"], check=False)
    if checkout_result.returncode != 0:
        log(("Error: failed to switch local checkout to `main`.", "red"))
        raise typer.Exit(checkout_result.returncode or 1)

    log("Pulling latest changes from the tracked remote…")
    pull_result = subprocess.run(["git", "-C", source_display, "pull", "--ff-only"], check=False)
    if pull_result.returncode != 0:
        log(("Error: `git pull --ff-only` failed.", "red"))
        raise typer.Exit(pull_result.returncode or 1)

    install_args = ["uv", "tool", "install", "--force"]
    if install_kind == INSTALL_KIND_EDITABLE:
        install_args.append("--editable")
    install_args.append(source_display)

    log("Reinstalling klaude from the updated local source…")
    install_result = subprocess.run(install_args, check=False)
    if install_result.returncode != 0:
        log((f"Error: reinstall failed (exit code {install_result.returncode}).", "red"))
        raise typer.Exit(install_result.returncode or 1)

    log("Update complete. Please re-run `klaude` to use the new version.")


def upgrade_command(
    check: bool = typer.Option(
        False,
        "--check",
        help="Check only, don't upgrade",
    ),
) -> None:
    """Upgrade to latest version"""
    from klaude_code.log import log
    from klaude_code.update import (
        INSTALL_KIND_DIRECT_URL,
        INSTALL_KIND_EDITABLE,
        INSTALL_KIND_LOCAL,
        PACKAGE_NAME,
        check_for_updates_blocking,
        get_install_source_path,
    )

    info = check_for_updates_blocking()

    if check:
        if info is None:
            log(("Error: `uv` is not available; cannot check for updates.", "red"))
            log(f"Install uv, then run `uv tool upgrade {PACKAGE_NAME}`.")
            raise typer.Exit(1)

        installed_display = info.installed or "unknown"
        latest_display = info.latest or "unknown"
        status = "update available" if info.update_available else "up to date"

        log(f"{PACKAGE_NAME} installed: {installed_display}")
        log(f"{PACKAGE_NAME} latest:    {latest_display}")
        log(f"Status: {status}")

        if info.install_kind == INSTALL_KIND_EDITABLE:
            log("Install mode: local editable")
        elif info.install_kind == INSTALL_KIND_LOCAL:
            log("Install mode: local path")
        elif info.install_kind == INSTALL_KIND_DIRECT_URL:
            log("Install mode: direct URL")

        if info.update_available:
            if info.install_kind in {INSTALL_KIND_EDITABLE, INSTALL_KIND_LOCAL}:
                log("PyPI has a newer release. Run `klaude upgrade` from a clean local checkout to update.")
            elif info.install_kind == INSTALL_KIND_DIRECT_URL:
                log("PyPI has a newer release. Reinstall from the source URL if needed.")
            else:
                log("Run `klaude upgrade` to upgrade.")

        return

    if info is not None and info.install_kind in {INSTALL_KIND_EDITABLE, INSTALL_KIND_LOCAL}:
        source_path = get_install_source_path()
        if source_path is None:
            if info.install_kind == INSTALL_KIND_EDITABLE:
                log(("Error: editable install source path is unavailable.", "red"))
            else:
                log(("Error: local path install source path is unavailable.", "red"))
            raise typer.Exit(1)

        _upgrade_local_git_install(info.install_kind, source_path)
        return

    if info is not None and info.install_kind == INSTALL_KIND_DIRECT_URL:
        log("Direct URL install detected; `klaude upgrade` cannot update it automatically.")
        log("Please reinstall from the source URL if needed.")
        return

    if shutil.which("uv") is None:
        log(("Error: `uv` not found in PATH.", "red"))
        log(f"To update, install uv and run `uv tool upgrade {PACKAGE_NAME}`.")
        raise typer.Exit(1)

    log(f"Running `uv tool upgrade {PACKAGE_NAME}`…")
    result = subprocess.run(["uv", "tool", "upgrade", PACKAGE_NAME], check=False)
    if result.returncode != 0:
        log((f"Error: update failed (exit code {result.returncode}).", "red"))
        raise typer.Exit(result.returncode or 1)

    log("Update complete. Please re-run `klaude` to use the new version.")


def register_self_upgrade_commands(app: typer.Typer) -> None:
    """Register self-update and version subcommands to the given Typer app."""

    app.command("upgrade")(upgrade_command)
    app.command("update", hidden=True)(upgrade_command)
    app.command("version", hidden=True)(version_command)
