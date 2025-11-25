"""Version checking utilities for klaude-code."""

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
    except Exception:
        return None


def _get_latest_version() -> str | None:
    """Get latest version from PyPI."""
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data.get("info", {}).get("version")
    except Exception:
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
    except Exception:
        return False


def check_for_updates() -> VersionInfo | None:
    """Check for updates to klaude-code.

    Returns VersionInfo if uv is available, None otherwise.
    Results are cached for CHECK_INTERVAL_SECONDS.
    """
    global _cached_version_info, _last_check_time

    if not _has_uv():
        return None

    now = time.time()

    with _check_lock:
        # Return cached result if still valid
        if _cached_version_info is not None and (now - _last_check_time) < CHECK_INTERVAL_SECONDS:
            return _cached_version_info

        installed = _get_installed_version()
        latest = _get_latest_version()

        update_available = False
        if installed and latest:
            update_available = _compare_versions(installed, latest)

        _cached_version_info = VersionInfo(
            installed=installed,
            latest=latest,
            update_available=update_available,
        )
        _last_check_time = now

        return _cached_version_info


def get_update_message() -> str | None:
    """Get update message if an update is available.

    Returns a formatted message string, or None if no update or uv unavailable.
    """
    info = check_for_updates()
    if info is None or not info.update_available:
        return None
    return f"New version available: {info.latest}. Please run `uv tool upgrade {PACKAGE_NAME}` to upgrade."
