"""Self-update and version utilities for klaude-code."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import urllib.request
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from typing import NamedTuple

import typer

from klaude_code.trace import log

PACKAGE_NAME = "klaude-code"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
CHECK_INTERVAL_SECONDS = 3600  # Check at most once per hour


class VersionInfo(NamedTuple):
    """Version check result."""

    installed: str | None
    latest: str | None
    update_available: bool


# Async check state
_cached_version_info: VersionInfo | None = None
_last_check_time: float = 0.0
_check_lock = threading.Lock()
_check_in_progress = False


def _has_uv() -> bool:
    """Check if uv command is available."""
    return shutil.which("uv") is not None


def _get_installed_version() -> str | None:
    """Get installed version of klaude-code via uv tool list."""
    try:
        result = subprocess.run(
            ["uv", "tool", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        # Parse output like "klaude-code v0.1.0"
        for line in result.stdout.splitlines():
            if line.startswith(PACKAGE_NAME):
                parts = line.split()
                if len(parts) >= 2:
                    ver = parts[1]
                    # Remove 'v' prefix if present
                    if ver.startswith("v"):
                        ver = ver[1:]
                    return ver
        return None
    except (OSError, subprocess.SubprocessError):
        return None


def _get_latest_version() -> str | None:
    """Get latest version from PyPI."""
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data.get("info", {}).get("version")
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse version string into comparable tuple of integers."""
    parts: list[int] = []
    for part in v.split("."):
        # Extract leading digits
        digits = ""
        for c in part:
            if c.isdigit():
                digits += c
            else:
                break
        if digits:
            parts.append(int(digits))
    return tuple(parts)


def _compare_versions(installed: str, latest: str) -> bool:
    """Return True if latest is newer than installed."""
    try:
        installed_tuple = _parse_version(installed)
        latest_tuple = _parse_version(latest)
        return latest_tuple > installed_tuple
    except ValueError:
        return False


def _do_version_check() -> None:
    """Perform version check in background thread."""
    global _cached_version_info, _last_check_time, _check_in_progress

    try:
        installed = _get_installed_version()
        latest = _get_latest_version()

        update_available = False
        if installed and latest:
            update_available = _compare_versions(installed, latest)

        with _check_lock:
            _cached_version_info = VersionInfo(
                installed=installed,
                latest=latest,
                update_available=update_available,
            )
            _last_check_time = time.time()
    finally:
        with _check_lock:
            _check_in_progress = False


def check_for_updates() -> VersionInfo | None:
    """Check for updates to klaude-code asynchronously.

    Returns cached VersionInfo immediately if available.
    Triggers background check if cache is stale or missing.
    Returns None if uv is not available or no cached result yet.
    """
    global _check_in_progress

    if not _has_uv():
        return None

    now = time.time()

    with _check_lock:
        cache_valid = _cached_version_info is not None and (now - _last_check_time) < CHECK_INTERVAL_SECONDS

        if cache_valid:
            return _cached_version_info

        # Start background check if not already in progress
        if not _check_in_progress:
            _check_in_progress = True
            thread = threading.Thread(target=_do_version_check, daemon=True)
            thread.start()

        # Return cached result (may be stale) or None if no cache yet
        return _cached_version_info


def get_update_message() -> str | None:
    """Get update message if an update is available.

    Returns immediately with cached result. Triggers async check if needed.
    Returns None if no update, uv unavailable, or check not complete yet.
    """
    info = check_for_updates()
    if info is None or not info.update_available:
        return None
    return f"New version available: {info.latest}. Please run `klaude upgrade` to upgrade."


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


def update_command(
    check: bool = typer.Option(
        False,
        "--check",
        help="Check for updates and exit without upgrading",
    ),
) -> None:
    """Upgrade klaude-code when installed via `uv tool`."""

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

        if info.update_available:
            log("Run `klaude upgrade` to upgrade.")

        return

    if shutil.which("uv") is None:
        log(("Error: `uv` not found in PATH.", "red"))
        log(f"To update, install uv and run `uv tool upgrade {PACKAGE_NAME}`.")
        raise typer.Exit(1)

    log(f"Running `uv tool upgrade {PACKAGE_NAME}`...")
    result = subprocess.run(["uv", "tool", "upgrade", PACKAGE_NAME], check=False)
    if result.returncode != 0:
        log((f"Error: update failed (exit code {result.returncode}).", "red"))
        raise typer.Exit(result.returncode or 1)

    log("Update complete. Please re-run `klaude` to use the new version.")


def register_self_update_commands(app: typer.Typer) -> None:
    """Register self-update and version subcommands to the given Typer app."""

    app.command("update")(update_command)
    app.command("upgrade", help="Alias for `klaude update`.")(update_command)
    app.command("version", help="Alias for `klaude --version`.")(version_command)


def check_for_updates_blocking() -> VersionInfo | None:
    """Check for updates to klaude-code synchronously.

    This is intended for CLI commands (e.g. `klaude update --check`) that need
    a deterministic result instead of the async cached behavior.

    Returns:
        VersionInfo if uv is available, otherwise None.
    """

    if not _has_uv():
        return None

    installed = _get_installed_version()
    latest = _get_latest_version()

    update_available = False
    if installed and latest:
        update_available = _compare_versions(installed, latest)

    return VersionInfo(
        installed=installed,
        latest=latest,
        update_available=update_available,
    )
