"""Self-update and version utilities for klaude-code."""

import shutil
import subprocess

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
    from klaude_code.update import _upgrade_git_install

    result = _upgrade_git_install(install_kind, source_path)
    if not result.performed:
        log((result.message or "Git upgrade failed", "red"))
        raise typer.Exit(1)
    log(result.message or "Update complete")


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
        UPDATE_SOURCE_GIT,
        UPGRADE_BRANCH,
        check_for_updates_blocking,
        get_install_source_path,
        get_installation_info,
    )

    if not check:
        # Each Klaude process loads the updated code on its next start.
        install = get_installation_info()
        if install.install_kind in {INSTALL_KIND_EDITABLE, INSTALL_KIND_LOCAL}:
            source = get_install_source_path()
            if source is None:
                log(("Error: local install source path is unavailable.", "red"))
                raise typer.Exit(1)
            _upgrade_local_git_install(install.install_kind, source)
            return

    try:
        info = check_for_updates_blocking()
    except RuntimeError as exc:
        log((f"Error: {exc}", "red"))
        raise typer.Exit(1) from None

    if check:
        if info is None:
            log(("Error: `uv` is not available; cannot check for updates.", "red"))
            log(f"Install uv, then run `uv tool upgrade {PACKAGE_NAME}`.")
            raise typer.Exit(1)

        tracks_git = info.update_source == UPDATE_SOURCE_GIT
        installed_display = info.installed or "unknown"
        latest_display = info.latest or "unknown"
        latest_label = f"origin/{UPGRADE_BRANCH}:" if tracks_git else "latest:   "
        status = "update available" if info.update_available else "up to date"

        log(f"{PACKAGE_NAME} installed: {installed_display}")
        log(f"{PACKAGE_NAME} {latest_label} {latest_display}")
        log(f"Status: {status}")

        if info.install_kind == INSTALL_KIND_EDITABLE:
            log("Install mode: local editable")
        elif info.install_kind == INSTALL_KIND_LOCAL:
            log("Install mode: local path")
        elif info.install_kind == INSTALL_KIND_DIRECT_URL:
            log("Install mode: direct URL")

        if info.update_available:
            if tracks_git:
                log(f"origin/{UPGRADE_BRANCH} has newer commits. Run `klaude upgrade` to update.")
            elif info.install_kind in {INSTALL_KIND_EDITABLE, INSTALL_KIND_LOCAL}:
                log("PyPI has a newer release. Run `klaude upgrade` from a clean local checkout to update.")
            elif info.install_kind == INSTALL_KIND_DIRECT_URL:
                log("PyPI has a newer release. Reinstall from the source URL if needed.")
            else:
                log("Run `klaude upgrade` to upgrade.")

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
