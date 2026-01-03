"""Non-interactive update check helpers.

This module is intentionally frontend-agnostic so it can be used by both the CLI
and terminal UI without introducing cross-layer imports.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import urllib.request
from typing import NamedTuple

PACKAGE_NAME = "klaude-code"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
CHECK_INTERVAL_SECONDS = 3600  # Check at most once per hour


class VersionInfo(NamedTuple):
    """Version check result."""

    installed: str | None
    latest: str | None
    update_available: bool


_cached_version_info: VersionInfo | None = None
_last_check_time: float = 0.0
_check_lock = threading.Lock()
_check_in_progress = False


def _has_uv() -> bool:
    return shutil.which("uv") is not None


def _get_installed_version() -> str | None:
    try:
        result = subprocess.run(
            ["uv", "tool", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        for line in result.stdout.splitlines():
            if line.startswith(PACKAGE_NAME):
                parts = line.split()
                if len(parts) >= 2:
                    ver = parts[1]
                    if ver.startswith("v"):
                        ver = ver[1:]
                    return ver
        return None
    except (OSError, subprocess.SubprocessError):
        return None


def _get_latest_version() -> str | None:
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data.get("info", {}).get("version")
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _parse_version(v: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in v.split("."):
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
    try:
        installed_tuple = _parse_version(installed)
        latest_tuple = _parse_version(latest)
        return latest_tuple > installed_tuple
    except ValueError:
        return False


def _do_version_check() -> None:
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
    """Check for updates asynchronously with caching."""
    global _check_in_progress

    if not _has_uv():
        return None

    now = time.time()
    with _check_lock:
        cache_valid = _cached_version_info is not None and (now - _last_check_time) < CHECK_INTERVAL_SECONDS
        if cache_valid:
            return _cached_version_info

        if not _check_in_progress:
            _check_in_progress = True
            thread = threading.Thread(target=_do_version_check, daemon=True)
            thread.start()

        return _cached_version_info


def get_update_message() -> str | None:
    """Return an update message if an update is available, otherwise None."""
    info = check_for_updates()
    if info is None or not info.update_available:
        return None
    return f"New version available: {info.latest}. Please run `klaude upgrade` to upgrade."


def check_for_updates_blocking() -> VersionInfo | None:
    """Check for updates synchronously (no caching)."""
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
