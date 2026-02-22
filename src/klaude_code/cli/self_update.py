"""Self-update and version utilities for klaude-code."""

import shutil
import subprocess
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version

import typer

from klaude_code.log import log
from klaude_code.update import (
    INSTALL_KIND_DIRECT_URL,
    INSTALL_KIND_EDITABLE,
    INSTALL_KIND_LOCAL,
    PACKAGE_NAME,
    check_for_updates_blocking,
    get_install_source_path,
)


def _print_version() -> None:
    try:
        ver = pkg_version(PACKAGE_NAME)
    except PackageNotFoundError:
        ver = "unknown"
    except (ValueError, TypeError):
        # Catch invalid package name format or type errors
        ver = "unknown"
    print(f"{PACKAGE_NAME} {ver}")


def version_option_callback(value: bool) -> None:
    """Show version and exit."""
    if value:
        _print_version()
        raise typer.Exit(0)


def version_command() -> None:
    """Show version and exit."""

    _print_version()


def upgrade_command(
    check: bool = typer.Option(
        False,
        "--check",
        help="Check only, don't upgrade",
    ),
) -> None:
    """Upgrade to latest version"""

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
            if info.install_kind == INSTALL_KIND_EDITABLE:
                log("PyPI has a newer release. Pull the local source and reinstall if needed.")
            elif info.install_kind == INSTALL_KIND_LOCAL:
                log("PyPI has a newer release. Update your local source and reinstall if needed.")
            elif info.install_kind == INSTALL_KIND_DIRECT_URL:
                log("PyPI has a newer release. Reinstall from the source URL if needed.")
            else:
                log("Run `klaude upgrade` to upgrade.")

        return

    if info is not None and info.install_kind in {INSTALL_KIND_EDITABLE, INSTALL_KIND_LOCAL, INSTALL_KIND_DIRECT_URL}:
        source_path = get_install_source_path()
        if info.install_kind == INSTALL_KIND_EDITABLE:
            log("Local editable install detected; `klaude upgrade` is only for PyPI index installs.")
        elif info.install_kind == INSTALL_KIND_LOCAL:
            log("Local path install detected; `klaude upgrade` is only for PyPI index installs.")
        else:
            log("Direct URL install detected; `klaude upgrade` is only for PyPI index installs.")
        if source_path:
            log(f"Source path: {source_path}")
        log("Please reinstall from your source if needed.")
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
