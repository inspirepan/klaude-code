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
from importlib.metadata import PackageNotFoundError, distribution
from typing import Any, NamedTuple, cast
from urllib.parse import urlparse

PACKAGE_NAME = "klaude-code"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
CHECK_INTERVAL_SECONDS = 3600  # Check at most once per hour

INSTALL_KIND_UNKNOWN = "unknown"
INSTALL_KIND_INDEX = "index"
INSTALL_KIND_DIRECT_URL = "direct_url"
INSTALL_KIND_LOCAL = "local"
INSTALL_KIND_EDITABLE = "editable"


class InstallationInfo(NamedTuple):
    """Current package installation metadata."""

    version: str | None
    install_kind: str
    source_url: str | None


class VersionInfo(NamedTuple):
    """Version check result."""

    installed: str | None
    latest: str | None
    update_available: bool
    install_kind: str = INSTALL_KIND_UNKNOWN


_cached_version_info: VersionInfo | None = None
_last_check_time: float = 0.0
_check_lock = threading.Lock()
_check_in_progress = False
_cached_installation_info: InstallationInfo | None = None

_auto_upgrade_lock = threading.Lock()
_auto_upgrade_attempted = False
_auto_upgrade_in_progress = False
_auto_upgrade_succeeded = False
_auto_upgrade_failed = False
_auto_upgrade_target_version: str | None = None


def _has_uv() -> bool:
    return shutil.which("uv") is not None


def _get_auto_upgrade_state() -> tuple[bool, bool, bool, str | None]:
    """Return auto-upgrade state as (in_progress, succeeded, failed, target_version)."""

    with _auto_upgrade_lock:
        return (
            _auto_upgrade_in_progress,
            _auto_upgrade_succeeded,
            _auto_upgrade_failed,
            _auto_upgrade_target_version,
        )


def _start_auto_upgrade_if_needed(info: VersionInfo) -> None:
    """Start a background `uv tool upgrade` once per process when appropriate."""
    global _auto_upgrade_attempted, _auto_upgrade_in_progress, _auto_upgrade_target_version

    if info.install_kind != INSTALL_KIND_INDEX:
        return
    if not info.update_available or not info.latest:
        return
    if not _has_uv():
        return

    with _auto_upgrade_lock:
        if _auto_upgrade_attempted:
            return
        _auto_upgrade_attempted = True
        _auto_upgrade_in_progress = True
        _auto_upgrade_target_version = info.latest

    thread = threading.Thread(target=_run_auto_upgrade, args=(info.latest,), daemon=True)
    thread.start()


def _run_auto_upgrade(target_version: str) -> None:
    """Run `uv tool upgrade` in background; changes apply on next process start."""
    global _auto_upgrade_in_progress, _auto_upgrade_succeeded, _auto_upgrade_failed
    global _cached_version_info, _last_check_time

    success = False
    try:
        result = subprocess.run(
            ["uv", "tool", "upgrade", PACKAGE_NAME],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        success = result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        success = False

    with _auto_upgrade_lock:
        _auto_upgrade_in_progress = False
        _auto_upgrade_succeeded = success
        _auto_upgrade_failed = not success

    if not success:
        return

    with _check_lock:
        current = _cached_version_info
        if current is None:
            return
        latest = target_version or current.latest
        _cached_version_info = VersionInfo(
            installed=latest or current.installed,
            latest=latest,
            update_available=False,
            install_kind=current.install_kind,
        )
        _last_check_time = time.time()


def _classify_install_kind(source_url: str | None, direct_url_data: dict[str, Any] | None) -> str:
    if isinstance(direct_url_data, dict):
        dir_info = direct_url_data.get("dir_info")
        if isinstance(dir_info, dict):
            dir_info_typed = cast(dict[str, Any], dir_info)
            if dir_info_typed.get("editable") is True:
                return INSTALL_KIND_EDITABLE

    if source_url is None:
        return INSTALL_KIND_INDEX
    if source_url.startswith("file://"):
        return INSTALL_KIND_LOCAL
    return INSTALL_KIND_DIRECT_URL


def get_installation_info() -> InstallationInfo:
    """Get current installation metadata for this running package."""
    global _cached_installation_info

    if _cached_installation_info is not None:
        return _cached_installation_info

    try:
        dist = distribution(PACKAGE_NAME)
    except PackageNotFoundError:
        info = InstallationInfo(version=None, install_kind=INSTALL_KIND_UNKNOWN, source_url=None)
        _cached_installation_info = info
        return info

    source_url: str | None = None
    direct_url_data: dict[str, Any] | None = None
    direct_url_text = dist.read_text("direct_url.json")
    if direct_url_text:
        try:
            parsed = json.loads(direct_url_text)
            if isinstance(parsed, dict):
                direct_url_data = cast(dict[str, Any], parsed)
                url = direct_url_data.get("url")
                if isinstance(url, str):
                    source_url = url
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    info = InstallationInfo(
        version=dist.version,
        install_kind=_classify_install_kind(source_url, direct_url_data),
        source_url=source_url,
    )
    _cached_installation_info = info
    return info


def get_display_version() -> str:
    """Get a user-facing version label.

    - normal install: ``2.16.0``
    - editable install: ``2.16.0 (editable)``
    """

    install_info = get_installation_info()
    version = install_info.version or "unknown"
    if install_info.install_kind == INSTALL_KIND_EDITABLE:
        return f"{version} (editable)"
    return version


def get_install_source_path() -> str | None:
    """Return local filesystem path when installed from a local file URL."""

    install_info = get_installation_info()
    source_url = install_info.source_url
    if source_url is None:
        return None

    parsed = urlparse(source_url)
    if parsed.scheme != "file":
        return None

    path = urllib.request.url2pathname(parsed.path)
    if parsed.netloc and parsed.netloc != "localhost":
        return f"//{parsed.netloc}{path}"
    return path


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
        install_info = get_installation_info()
        installed = install_info.version or _get_installed_version()
        latest = _get_latest_version()

        update_available = False
        if installed and latest:
            update_available = _compare_versions(installed, latest)

        with _check_lock:
            _cached_version_info = VersionInfo(
                installed=installed,
                latest=latest,
                update_available=update_available,
                install_kind=install_info.install_kind,
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
    in_progress, succeeded, failed, target_version = _get_auto_upgrade_state()

    if in_progress:
        target = target_version or (info.latest if info else "latest")
        return f"Updating to {target} in background; changes apply on next launch."

    if succeeded:
        target = target_version or "latest"
        return f"Background update to {target} completed. Restart `klaude` to use it."

    if info is None:
        return None

    if info.install_kind == INSTALL_KIND_INDEX and info.update_available:
        _start_auto_upgrade_if_needed(info)
        in_progress, succeeded, failed, target_version = _get_auto_upgrade_state()
        if in_progress:
            return f"New version {info.latest} detected. Updating in background; changes apply on next launch."
        if succeeded:
            target = target_version or info.latest or "latest"
            return f"Background update to {target} completed. Restart `klaude` to use it."
        if failed:
            return f"New version available: {info.latest}. Auto-update failed; run `klaude upgrade`."

    if not info.update_available:
        return None

    if info.install_kind == INSTALL_KIND_EDITABLE:
        return f"PyPI {info.latest} available. Local editable install detected; pull latest source."

    if info.install_kind == INSTALL_KIND_LOCAL:
        return f"PyPI {info.latest} available. Local path install detected; update your local source."

    return f"New version available: {info.latest}. Please run `klaude upgrade` to upgrade."


def check_for_updates_blocking() -> VersionInfo | None:
    """Check for updates synchronously (no caching)."""
    if not _has_uv():
        return None

    install_info = get_installation_info()
    installed = install_info.version or _get_installed_version()
    latest = _get_latest_version()

    update_available = False
    if installed and latest:
        update_available = _compare_versions(installed, latest)

    return VersionInfo(
        installed=installed,
        latest=latest,
        update_available=update_available,
        install_kind=install_info.install_kind,
    )
